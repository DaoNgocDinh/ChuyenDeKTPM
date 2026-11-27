"""Host cancellation and reconciliation. No recovery path re-dispatches an uncertain patch."""

import contextvars
import json
import os
import signal
import subprocess
import time
from contextlib import contextmanager

from .approvals import ApprovalService
from .contracts import ArtifactRef
from .lifecycle import Checkpoint, recovery_action
from .storage import StorageConflict, encode, new_id
from .workspace import Workspace


CURRENT_SIGNAL = contextvars.ContextVar("current_run_signal", default=None)
READ_ONLY_ROLES = frozenset({"orchestrator", "requirement", "architecture", "planning"})


class OperationCancelled(RuntimeError):
    pass


def _active_resources(repo, project_id, run_id):
    events = repo.for_run(project_id, run_id).records("events")
    live = set()
    for row in sorted(events, key=lambda item: item["id"]):
        if row["event_type"] in ("resource.started", "resource.stopped"):
            key = json.loads(row["payload_json"])["id"]
            if row["event_type"] == "resource.started":
                live.add(key)
            else:
                live.discard(key)
    return live


def _event(repo, run_id, name, payload):
    repo._db.execute("INSERT INTO events(run_id,event_type,payload_json) VALUES (?,?,?)",
                     (run_id, name, encode(payload)))


class RunSignal:
    def __init__(self, database, project_id, run_id, token):
        self.database = database
        self.project_id, self.run_id, self.token = project_id, run_id, token

    def is_set(self):
        with self.database.transaction() as repo:
            try:
                repo.worker_run(self.project_id, self.run_id, self.token)
            except (KeyError, StorageConflict):
                return True
        return False

    def wait(self, timeout=0):
        if self.is_set():
            return True
        if timeout and timeout > 0:
            time.sleep(timeout)
            return self.is_set()
        return False

    @contextmanager
    def observe(self):
        binding = CURRENT_SIGNAL.set(self)
        try:
            yield self
        finally:
            CURRENT_SIGNAL.reset(binding)

    def started(self, kind):
        key = new_id()
        with self.database.transaction(write=True) as repo:
            writer = repo.worker_run(self.project_id, self.run_id, self.token)
            writer.add_event("resource.started", {"id": key, "kind": kind})
        return key

    def stopped(self, key, *, confirmed):
        with self.database.transaction(write=True) as repo:
            run = repo.get_run(self.project_id, self.run_id)
            live = _active_resources(repo, self.project_id, self.run_id)
            if key not in live:
                raise StorageConflict("Unknown active resource")
            name = "resource.stopped" if confirmed else "resource.stop_unconfirmed"
            _event(repo, self.run_id, name, {"id": key})
            checkpoint = json.loads(run["checkpoint_json"] or "{}")
            if confirmed and live == {key} and checkpoint.get("cancel_requested"):
                repo._db.execute("UPDATE runs SET status='cancelled', ended_at=CURRENT_TIMESTAMP WHERE id=?",
                                 (self.run_id,))
                _event(repo, self.run_id, "cancelled", {"reason": "all_resources_stopped"})


def _terminate_tree(process):
    if os.name == "nt":
        if process.poll() is None:
            stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                     capture_output=True, timeout=12)
            if stopped.returncode and process.poll() is None:
                raise RuntimeError("Cannot confirm child tree termination")
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


def controlled_command(argv, *, cwd, env, input, timeout):
    """Used for the isolated provider CLI when a host run owns the process."""
    owner = CURRENT_SIGNAL.get()
    if owner is None:
        return subprocess.run(argv, cwd=cwd, env=env, input=input, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    key = owner.started("model_cli")
    confirmed = False
    process = None
    try:
        if owner.is_set():
            raise OperationCancelled("Run cancelled before process creation")
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, encoding="utf-8", errors="replace", **options)
        deadline = time.monotonic() + timeout
        pending = input
        while True:
            if owner.is_set():
                raise OperationCancelled("Run cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                out, err = process.communicate(pending, timeout=min(0.15, remaining))
                confirmed = True
                return subprocess.CompletedProcess(argv, process.returncode, out, err)
            except subprocess.TimeoutExpired:
                pending = None
    finally:
        if process is None:
            confirmed = True
        try:
            if process is not None and not confirmed:
                _terminate_tree(process)
                process.communicate(timeout=3)
                confirmed = True
        finally:
            owner.stopped(key, confirmed=confirmed)


class RecoveryService:
    def __init__(self, database, store):
        self.database, self.store = database, store
        self.gates = ApprovalService(database)

    def cancel(self, project_id, run_id, *, wait_seconds=0):
        with self.database.transaction(write=True) as repo:
            run = repo.get_run(project_id, run_id)
            if run["status"] == "cancelled":
                return {"status": "cancelled", "reason": "cancelled"}
            if run["status"] in {"completed","failed"}:
                raise StorageConflict("Terminal run cannot be cancelled")
            checkpoint = json.loads(run["checkpoint_json"] or "{}")
            checkpoint["cancel_requested"] = True
            pending = _active_resources(repo, project_id, run_id)
            status = "pending_recovery" if pending else "cancelled"
            repo._db.execute("UPDATE runs SET status=?,checkpoint_json=?,worker_lease=NULL,lease_expires_at=NULL,"
                             "ended_at=CASE WHEN ?='cancelled' THEN CURRENT_TIMESTAMP ELSE ended_at END WHERE id=?",
                             (status, encode(checkpoint), status, run_id))
            _event(repo, run_id, "cancel.requested", {"pending_resources": len(pending)})
        deadline = time.monotonic() + max(0, wait_seconds)
        while status != "cancelled" and time.monotonic() < deadline:
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            with self.database.transaction() as repo:
                status = repo.get_run(project_id, run_id)["status"]
        return {"status": status, "reason": "cancelled" if status == "cancelled" else "awaiting_process_cleanup"}

    def _evidence(self, project_id, run_id, checkpoint, steps, tasks=(), tool_calls=()):
        if any(t["status"] == "blocked" for t in tasks):
            raise ValueError("task_blocked_needs_human")
        for raw in checkpoint.get("input_refs", []):
            ref = ArtifactRef.model_validate(raw)
            if ref.run_id != run_id:
                raise ValueError("input_run_changed")
            self.store.read(project_id, run_id, ref.artifact_id, ref.version, ref.sha256)
        gates = checkpoint.get("approved_gates", {})
        for gate, refs in gates.items():
            if not self.gates.is_gate_approved(project_id, run_id, gate, [ArtifactRef.model_validate(r) for r in refs]):
                raise ValueError("approval_changed")
        journal = self.store.root / project_id / run_id / "logs" / "pending-patch.json"
        if journal.exists():
            raise ValueError("incomplete_patch_journal")
        effect = checkpoint.get("pending_effect")
        active = [s for s in steps if s["status"] == "started"]
        if not effect:
            if active:
                if (
                    len(active) == 1
                    and active[0]["agent_role"] in READ_ONLY_ROLES
                    and not any(tc["step_id"] == active[0]["id"] for tc in tool_calls)
                    and (not checkpoint.get("step_id") or checkpoint.get("step_id") == active[0]["id"])
                ):
                    if checkpoint.get("output_commit"):
                        ws = Workspace(self.store.root, project_id, run_id)
                        if ws.head() != checkpoint["output_commit"] or ws.status():
                            raise ValueError("workspace_changed")
                    elif (self.store.root / project_id / run_id / ".git").exists():
                        ws = Workspace(self.store.root, project_id, run_id)
                        if ws.status():
                            raise ValueError("workspace_changed")
                    return {"_read_only_step_id": active[0]["id"]}
                raise ValueError("missing_operation_receipt")
            if checkpoint.get("phase") == "before":
                raise ValueError("missing_operation_receipt")
            if checkpoint.get("output_commit"):
                ws = Workspace(self.store.root, project_id, run_id)
                if ws.head() != checkpoint["output_commit"] or ws.status():
                    raise ValueError("workspace_changed")
            return None
        if not {"requirements","architecture_plan"} <= gates.keys():
            raise ValueError("approval_missing")
        if not effect.get("patch_hash") or not effect.get("input_commit") or not effect.get("operation_id"):
            raise ValueError("incomplete_checkpoint")
        ws = Workspace(self.store.root, project_id, run_id)
        receipt = ws.operation_receipt(effect["operation_id"])
        if not receipt or receipt.get("task_id") != effect.get("task_id") or ws.status():
            raise ValueError("missing_or_mismatched_receipt")
        expected = Checkpoint(effect["operation_id"], effect["input_commit"], effect["patch_hash"], effect.get("output_commit"))
        actual = Checkpoint(receipt["operation_id"], receipt["input_commit"], receipt["patch_hash"], receipt.get("output_commit"))
        if recovery_action(expected, actual, ws.head()) != "advance_without_replay":
            raise ValueError("operation_commit_or_patch_changed")
        if (ws.git("rev-parse", actual.output_commit + "^").strip() != expected.input_commit
                or ws.diff(expected.input_commit, actual.output_commit) != receipt["diff"]):
            raise ValueError("git_diff_changed")
        if len(active) != 1 or active[0]["id"] != effect.get("step_id") or active[0]["task_id"] != effect["task_id"]:
            raise ValueError("step_or_task_changed")
        if active[0]["agent_role"] != "dev":
            raise ValueError("unverified_tester_or_other_effect")
        return receipt

    def resume(self, project_id, run_id):
        with self.database.transaction() as repo:
            run = repo.get_run(project_id, run_id)
            checkpoint = json.loads(run["checkpoint_json"] or "{}")
            reader = repo.for_run(project_id, run_id)
            steps = reader.records("agent_steps")
            tasks = reader.records("tasks")
            tool_calls = reader.records("tool_calls")
            live = _active_resources(repo, project_id, run_id)
        if run["status"] not in ("pending_recovery", "needs_human_review") or checkpoint.get("cancel_requested"):
            raise StorageConflict("Run cannot be resumed from this state")
        if run["worker_lease"] is not None or live:
            return {"status": run["status"], "reason": "active_lease_or_process"}
        try:
            evidence = self._evidence(project_id, run_id, checkpoint, steps, tasks, tool_calls)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc).isidentifier() else "evidence_unavailable"
            with self.database.transaction(write=True) as repo:
                _event(repo, run_id, "recovery.blocked", {"reason": reason})
            return {"status": run["status"], "reason": reason}
        read_only_step_id = evidence.get("_read_only_step_id") if isinstance(evidence, dict) else None
        receipt = None if read_only_step_id else evidence
        with self.database.transaction(write=True) as repo:
            current = repo.get_run(project_id, run_id)
            if (current["status"], current["checkpoint_json"], current["worker_lease"]) != (
                    run["status"], run["checkpoint_json"], None):
                raise StorageConflict("Run changed during reconciliation")
            if read_only_step_id:
                step_row = repo._db.execute(
                    "SELECT status, agent_role FROM agent_steps WHERE run_id=? AND id=?",
                    (run_id, read_only_step_id),
                ).fetchone()
                has_tools = repo._db.execute(
                    "SELECT 1 FROM tool_calls WHERE run_id=? AND step_id=? LIMIT 1",
                    (run_id, read_only_step_id),
                ).fetchone()
                if not step_row or step_row["status"] != "started" or step_row["agent_role"] not in READ_ONLY_ROLES or has_tools:
                    return {"status": current["status"], "reason": "step_or_task_changed"}
                repo._db.execute("UPDATE agent_steps SET status='reconciled' WHERE run_id=? AND id=?",
                                 (run_id, read_only_step_id))
                checkpoint["phase"] = "after"
            elif receipt:
                effect = checkpoint["pending_effect"]
                operation = repo._db.execute(
                    "SELECT * FROM tool_calls WHERE run_id=? AND operation_id=? AND step_id=?",
                    (run_id, effect["operation_id"], effect["step_id"]),
                ).fetchone()
                task = repo._db.execute("SELECT status FROM tasks WHERE run_id=? AND id=?",
                                        (run_id, effect["task_id"])).fetchone()
                if (not operation or operation["tool_name"] != "workspace.apply_patch" or operation["status"] not in {"started","ok"}
                        or not task or task["status"] != "in_progress"):
                    return {"status": current["status"], "reason": "task_or_operation_record_changed"}
                checkpoint["recovered_patch"] = {k: receipt[k] for k in
                    ("operation_id", "task_id", "input_commit", "output_commit", "patch_hash")}
                checkpoint["phase"] = "after"
                repo._db.execute("UPDATE agent_steps SET status='reconciled' WHERE run_id=? AND id=?",
                                 (run_id, effect["step_id"]))
                repo._db.execute("UPDATE tool_calls SET status='ok' WHERE run_id=? AND operation_id=?",
                                 (run_id, effect["operation_id"]))
                repo._db.execute("UPDATE tasks SET status='waiting_test' WHERE run_id=? AND id=?",
                                 (run_id, effect["task_id"]))
                checkpoint.pop("pending_effect")
            repo._db.execute("UPDATE runs SET status='queued',checkpoint_json=? WHERE id=?", (encode(checkpoint), run_id))
            _event(repo, run_id, "recovery.reconciled", {
                "skip_applied_patch": bool(receipt),
                **({"reconciled_read_only_step": read_only_step_id} if read_only_step_id else {}),
            })
        return {"status": "queued", "reason": "resume_at_tester" if receipt else "resume_at_checkpoint"}
