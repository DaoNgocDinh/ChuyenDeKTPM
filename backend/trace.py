"""SUPPORT MODULE (draft prior to I17/I18) for I21 event audit and FR -> task -> patch -> test trace.

Provides redacted audit event recording with error taxonomy (schema/policy/environment/code),
stable D10-compatible cursor pagination, artifact version lineage queries, and run-scoped
requirement traceability verification directly on top of I02/I03/I13.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from backend.storage import Database


ERROR_CATEGORIES = frozenset({"schema", "policy", "environment", "code"})
SENSITIVE_KEY_TOKENS = ("api_key", "apikey", "secret", "token", "password", "authorization", "credential")


@dataclass(frozen=True)
class FRTraceChain:
    run_id: str
    fr_id: str
    task_ids: tuple[str, ...]
    patch_artifacts: tuple[dict[str, object], ...]
    test_reports: tuple[dict[str, object], ...]
    complete: bool
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def redact_payload(value: Any, *, secrets: Iterable[str] = ()) -> Any:
    """Recursively redact sensitive keys and explicit host canary values before persistence."""
    canary_list = tuple(s for s in secrets if s)

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            cleaned: dict[str, Any] = {}
            for k, v in node.items():
                key_low = str(k).lower()
                if any(tok in key_low for tok in SENSITIVE_KEY_TOKENS):
                    cleaned[str(k)] = "[REDACTED]"
                else:
                    cleaned[str(k)] = _walk(v)
            return cleaned
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, str):
            out = node
            for secret in canary_list:
                if secret in out:
                    out = out.replace(secret, "[REDACTED]")
            return out
        return node

    return _walk(value)


class TraceAuditService:
    """Host-owned audit and traceability service for I21."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def record_event(
        self,
        project_id: str,
        run_id: str,
        lease: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        correlation_id: str,
        step_id: str | None = None,
        error_category: str | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        if not correlation_id.strip():
            raise ValueError("correlation_id is required for audit events")
        if error_category is not None and error_category not in ERROR_CATEGORIES:
            raise ValueError(f"Unsupported error_category {error_category!r}; expected one of {sorted(ERROR_CATEGORIES)}")

        body = redact_payload(dict(payload), secrets=secrets)
        body["correlation_id"] = correlation_id
        if error_category is not None:
            body["error_category"] = error_category

        with self.database.transaction(write=True) as repo:
            writer = repo.worker_run(project_id, run_id, lease)
            writer.add_event(event_type, body, step_id=step_id)

    def poll_events(
        self,
        project_id: str,
        run_id: str,
        *,
        after: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        """Return D10-compatible cursor page preserving cursor unchanged on empty results."""
        with self.database.transaction() as repo:
            rows = repo.for_run(project_id, run_id).events_after(cursor=after, limit=limit)
        items = [
            {
                "sequence": row["id"],
                "event_type": row["event_type"],
                "step_id": row["step_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        next_cursor = items[-1]["sequence"] if items else after
        return {"items": items, "next_cursor": next_cursor}

    def link_fr_chain(
        self,
        project_id: str,
        run_id: str,
        lease: str,
        *,
        fr_id: str,
        task_id: str,
        patch_artifact_id: str | None = None,
        test_report_id: str | None = None,
        evidence_uri: str,
    ) -> None:
        """Persist validated FR -> task -> patch -> test links within the same run."""
        if not fr_id.strip() or not evidence_uri.strip():
            raise ValueError("fr_id and evidence_uri are required")
        with self.database.transaction(write=True) as repo:
            writer = repo.worker_run(project_id, run_id, lease)
            task = next((t for t in writer.records("tasks") if t["id"] == task_id), None)
            if not task or fr_id not in json.loads(task["requirement_refs_json"]):
                raise ValueError("Task does not implement this requirement")
            if patch_artifact_id is not None and not any(
                a["id"] == patch_artifact_id and a["type"] == "patch" for a in writer.records("artifacts")
            ):
                raise ValueError("Unknown patch for this run")
            if test_report_id is not None and not any(
                r["id"] == test_report_id and r["task_id"] == task_id for r in writer.records("test_reports")
            ):
                raise ValueError("Report does not belong to this task")
            writer.add_trace("requirement", fr_id, "task", task_id, evidence_uri)
            if patch_artifact_id is not None:
                writer.add_trace("task", task_id, "patch", patch_artifact_id, evidence_uri)
            if test_report_id is not None:
                source_type = "patch" if patch_artifact_id is not None else "task"
                source_id = patch_artifact_id if patch_artifact_id is not None else task_id
                writer.add_trace(source_type, source_id, "test", test_report_id, evidence_uri)

    def trace_requirement(self, project_id: str, run_id: str, fr_id: str) -> FRTraceChain:
        with self.database.transaction() as repo:
            reader = repo.for_run(project_id, run_id)
            links = reader.records("trace_links")
            tasks_by_id = {t["id"]: t for t in reader.records("tasks")}
            artifacts_by_id = {a["id"]: a for a in reader.records("artifacts")}
            reports_by_id = {r["id"]: r for r in reader.records("test_reports")}

        linked_tasks = sorted(
            {
                ln["target_id"]
                for ln in links
                if ln["source_type"] == "requirement"
                and ln["source_id"] == fr_id
                and ln["target_type"] == "task"
                and ln["target_id"] in tasks_by_id
            }
        )
        patch_ids = sorted(
            {
                ln["target_id"]
                for ln in links
                if ln["source_type"] == "task"
                and ln["source_id"] in linked_tasks
                and ln["target_type"] in {"patch", "artifact"}
                and ln["target_id"] in artifacts_by_id
            }
        )
        report_ids = sorted(
            {
                ln["target_id"]
                for ln in links
                if (
                    (ln["source_type"] in {"patch", "artifact"} and ln["source_id"] in patch_ids)
                    or (ln["source_type"] == "task" and ln["source_id"] in linked_tasks)
                )
                and ln["target_type"] in {"test", "report"}
                and ln["target_id"] in reports_by_id
            }
        )

        patches = tuple(
            {
                "artifact_id": artifacts_by_id[pid]["id"],
                "type": artifacts_by_id[pid]["type"],
                "version": artifacts_by_id[pid]["version"],
                "sha256": artifacts_by_id[pid]["sha256"],
                "uri": artifacts_by_id[pid]["uri"],
            }
            for pid in patch_ids
        )
        reports = tuple(
            {
                "report_id": reports_by_id[rid]["id"],
                "task_id": reports_by_id[rid]["task_id"],
                "suite_id": reports_by_id[rid]["suite_id"],
                "commit_hash": reports_by_id[rid]["commit_hash"],
                "exit_code": reports_by_id[rid]["exit_code"],
                "passed": reports_by_id[rid]["passed"],
                "failed": reports_by_id[rid]["failed"],
                "skipped": reports_by_id[rid]["skipped"],
                "errors": reports_by_id[rid]["errors"],
                "report_uri": reports_by_id[rid]["report_uri"],
            }
            for rid in report_ids
        )

        gaps: list[str] = []
        if not linked_tasks:
            gaps.append("missing_task")
        if not patches:
            gaps.append("missing_patch")
        if not reports:
            gaps.append("missing_test_report")
        for task in linked_tasks:
            own_patches = {ln["target_id"] for ln in links if ln["source_type"] == "task"
                           and ln["source_id"] == task and ln["target_type"] == "patch"
                           and artifacts_by_id.get(ln["target_id"], {}).get("type") == "patch"}
            connected = any(ln["source_type"] == "patch" and ln["source_id"] in own_patches
                            and ln["target_type"] == "test"
                            and reports_by_id.get(ln["target_id"], {}).get("task_id") == task for ln in links)
            if not connected:
                gaps.append("incomplete_task_chain:" + task)

        return FRTraceChain(
            run_id=run_id,
            fr_id=fr_id,
            task_ids=tuple(linked_tasks),
            patch_artifacts=patches,
            test_reports=reports,
            complete=not gaps,
            gaps=tuple(gaps),
        )

    def audit_requirements_coverage(
        self,
        project_id: str,
        run_id: str,
        fr_ids: Iterable[str],
    ) -> dict[str, object]:
        chains = [self.trace_requirement(project_id, run_id, fr) for fr in fr_ids]
        complete_count = sum(1 for c in chains if c.complete)
        return {
            "run_id": run_id,
            "linked_complete": complete_count,
            "total": len(chains),
            "incomplete_frs": [c.fr_id for c in chains if not c.complete],
            "chains": [c.to_dict() for c in chains],
        }

    def artifact_version_history(
        self,
        project_id: str,
        run_id: str,
        *,
        artifact_type: str | None = None,
    ) -> list[dict[str, object]]:
        with self.database.transaction() as repo:
            rows = repo.for_run(project_id, run_id).records("artifacts")
        filtered = [r for r in rows if artifact_type is None or r["type"] == artifact_type]
        filtered.sort(key=lambda r: (r["type"], r["version"], r["id"]))
        return [
            {
                "artifact_id": r["id"],
                "type": r["type"],
                "version": r["version"],
                "sha256": r["sha256"],
                "created_by": r["created_by"],
                "parent_refs": json.loads(r["parent_refs_json"]),
            }
            for r in filtered
        ]
