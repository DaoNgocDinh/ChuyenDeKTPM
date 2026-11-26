"""A durable queue with short transactions and token-fenced worker operations."""

import json
import logging
import threading
from dataclasses import dataclass

from .lifecycle import RunState, run_transition
from .recovery import OperationCancelled, RunSignal
from .storage import Repository, StorageConflict, encode, new_id


logger = logging.getLogger(__name__)
PERSISTED_TRANSITION = "host_transition_persisted"


@dataclass(frozen=True)
class Lease:
    project_id: str
    run_id: str
    token: str


class Queue:
    def __init__(self, database):
        self.database = database

    def enqueue(self, project_id, key, config, budget):
        with self.database.transaction(write=True) as repo:
            return repo.create_run(project_id, key, config, budget)

    @staticmethod
    def _duration(seconds):
        if type(seconds) is not int or seconds < 1:
            raise ValueError("Lease duration must be a positive number of seconds")
        return f"+{seconds} seconds"

    def claim(self, lease_seconds=30):
        duration = self._duration(lease_seconds)
        with self.database._connection_transaction(write=True) as db:
            current = db.execute(
                "SELECT id, lease_expires_at IS NOT NULL AND "
                "julianday(lease_expires_at)>julianday('now') AS live FROM runs WHERE status='running'"
            ).fetchone()
            if current:
                if current["live"]:
                    return None
                db.execute("UPDATE runs SET status='pending_recovery',worker_lease=NULL,lease_expires_at=NULL "
                           "WHERE id=?", (current["id"],))
                db.execute("INSERT INTO events(run_id,event_type,payload_json) VALUES (?,'lease_expired','{}')",
                           (current["id"],))
            next_run = db.execute(
                "SELECT id,project_id FROM runs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1"
            ).fetchone()
            if next_run is None:
                return None
            lease = Lease(next_run["project_id"], next_run["id"], new_id())
            db.execute("UPDATE runs SET status='running',worker_lease=?,"
                       "lease_expires_at=strftime('%Y-%m-%dT%H:%M:%fZ','now',?),"
                       "started_at=COALESCE(started_at,CURRENT_TIMESTAMP) WHERE id=?",
                       (lease.token, duration, lease.run_id))
            db.execute("INSERT INTO events(run_id,event_type,payload_json) VALUES (?,'claimed','{}')",
                       (lease.run_id,))
            return lease

    def heartbeat(self, lease, lease_seconds=30):
        duration = self._duration(lease_seconds)
        with self.database._connection_transaction(write=True) as db:
            Repository(db).worker_run(lease.project_id, lease.run_id, lease.token)
            db.execute("UPDATE runs SET lease_expires_at=strftime('%Y-%m-%dT%H:%M:%fZ','now',?) WHERE id=?",
                       (duration, lease.run_id))

    def start_step(self, lease, step_id, role, attempt, inputs, checkpoint, task_id=None):
        if not isinstance(checkpoint, dict) or not checkpoint.get("operation_id"):
            raise ValueError("Checkpoint must name the operation before dispatch")
        with self.database._connection_transaction(write=True) as db:
            work = Repository(db).worker_run(lease.project_id, lease.run_id, lease.token)
            if db.execute("SELECT 1 FROM agent_steps WHERE run_id=? AND status='started' LIMIT 1",
                          (lease.run_id,)).fetchone():
                raise StorageConflict("Run already has an unfinished step")
            work.start_step(step_id, role, attempt, inputs, task_id)
            previous = json.loads(Repository(db).get_run(lease.project_id, lease.run_id)["checkpoint_json"] or "{}")
            # The gate history persists across steps. Operation fields only belong to the active step.
            inherited = {k: v for k, v in previous.items() if k in
                         ("approved_gates", "revision_route", "stale_artifacts", "pending_questions", "recovered_patch")}
            saved = {**inherited, **checkpoint, "step_id": step_id, "phase": "before"}
            db.execute("UPDATE runs SET checkpoint_json=? WHERE id=?", (encode(saved), lease.run_id))
            work.add_event("step_started", {"operation_id": checkpoint["operation_id"]}, step_id)

    def finish_step(self, lease, step_id, status, outputs, checkpoint, usage=None):
        if status == "started" or not status or not isinstance(checkpoint, dict):
            raise ValueError("Finished step must have a final status and checkpoint")
        with self.database._connection_transaction(write=True) as db:
            repo = Repository(db)
            work = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            previous = json.loads(repo.get_run(lease.project_id, lease.run_id)["checkpoint_json"] or "{}")
            if (previous.get("phase") != "before" or previous.get("step_id") != step_id
                    or previous.get("operation_id") != checkpoint.get("operation_id")):
                raise StorageConflict("Step or operation differs from the checkpoint")
            work.finish_step(step_id, status, outputs, usage)
            saved = {**previous, **checkpoint, "step_id": step_id, "phase": "after"}
            db.execute("UPDATE runs SET checkpoint_json=? WHERE id=?", (encode(saved), lease.run_id))
            work.add_event("step_finished", {"status": status, "operation_id": saved["operation_id"]}, step_id)

    def release(self, lease, event):
        state = run_transition(RunState.RUNNING, event)
        with self.database._connection_transaction(write=True) as db:
            work = Repository(db).worker_run(lease.project_id, lease.run_id, lease.token)
            pending = db.execute("SELECT 1 FROM agent_steps WHERE run_id=? AND status='started' LIMIT 1",
                                 (lease.run_id,)).fetchone()
            if pending and state not in {RunState.RECOVERY, RunState.CANCELLED}:
                raise StorageConflict("Unresolved step must be reconciled before releasing the run")
            work.add_event(event, {"status": str(state)})
            terminal = state in {RunState.CANCELLED, RunState.FAILED, RunState.COMPLETED}
            db.execute("UPDATE runs SET status=?,worker_lease=NULL,lease_expires_at=NULL,"
                       "ended_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE ended_at END WHERE id=?",
                       (state, terminal, lease.run_id))
        return state


class Worker:
    """Runs one injected orchestration handler at a time outside the HTTP process."""

    def __init__(self, queue, handler, *, lease_seconds=30):
        queue._duration(lease_seconds)
        self.queue, self.handler, self.lease_seconds = queue, handler, lease_seconds

    def run_one(self):
        lease = self.queue.claim(self.lease_seconds)
        if lease is None:
            return False
        done = threading.Event()
        lost = threading.Event()

        def keep_alive():
            while not done.wait(self.lease_seconds / 3):
                try:
                    self.queue.heartbeat(lease, self.lease_seconds)
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=keep_alive, daemon=True)
        thread.start()
        signal = RunSignal(self.queue.database, lease.project_id, lease.run_id, lease.token)
        try:
            with signal.observe():
                event = self.handler(lease, lost)
            if event == PERSISTED_TRANSITION:
                with self.queue.database.transaction() as repo:
                    state = repo.get_run(lease.project_id, lease.run_id)
                if state["worker_lease"] == lease.token:
                    raise StorageConflict("Handler returned before persisting its transition")
            elif lost.is_set() or signal.is_set():
                raise StorageConflict("Worker lost its lease during dispatch")
            else:
                self.queue.release(lease, event)
        except OperationCancelled:
            with self.queue.database.transaction() as repo:
                state = repo.get_run(lease.project_id, lease.run_id)
            if state["status"] == "running" and state["worker_lease"] == lease.token:
                self.queue.release(lease, "cancel")
            return True
        except Exception:
            # An exception cannot prove an external operation never took effect.
            try:
                self.queue.release(lease, "effects_uncertain")
            except StorageConflict:
                pass  # Already fenced. The active owner or expiry sweep records the state.
            raise
        finally:
            done.set()
            thread.join()
        return True

    def run_forever(self, stop, poll_seconds=1):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        while not stop.is_set():
            try:
                processed = self.run_one()
            except Exception as exc:
                # Provider or model error messages can contain credentials or prompt fragments.
                logger.error("Worker dispatch stopped (%s)", type(exc).__name__)
                processed = False
            if not processed:
                stop.wait(poll_seconds)
