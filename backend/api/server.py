"""Local loopback FastAPI server implementing the D10 platform API contract (I22)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.approvals import ApprovalService, ApprovalVersionConflict, InvalidGateTransition
from backend.artifacts import ArtifactStore
from backend.contracts import ArtifactRef as ContractArtifactRef
from backend.exporter import ExportPathError, SecretLeakError, build_export_zip
from backend.lifecycle import RunState
from backend.recovery import RecoveryService
from backend.storage import Database, StorageConflict, encode, new_id
from backend.trace import TraceAuditService
from backend.worker import Queue
from backend.workspace import Workspace


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
JSON_ARTIFACT_KINDS = frozenset({
    "requirements", "architecture", "plan", "dev_result",
    "test_report", "bug_report", "runner_output", "log",
})

ErrorCode = Literal[
    "not_found",
    "approval_version_conflict",
    "invalid_transition",
    "tool_denied",
    "budget_exceeded",
    "invalid_request",
    "idempotency_conflict",
]


class ApiError(Exception):
    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProjectRequest(StrictModel):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def non_blank(self) -> CreateProjectRequest:
        if not self.name.strip() or not self.brief.strip():
            raise ValueError("Tên dự án và brief không được để trống.")
        return self


class CreateRunRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    configuration_ref: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def non_blank(self) -> CreateRunRequest:
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key không được để trống.")
        return self


class ArtifactRefInput(StrictModel):
    artifact_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApprovalRequest(StrictModel):
    gate: Literal["requirements", "architecture_plan"]
    artifacts: list[ArtifactRefInput] = Field(min_length=1, max_length=2)
    decision: Literal["approve", "request_changes"]
    comment: str = ""

    @model_validator(mode="after")
    def check_gate_rules(self) -> ApprovalRequest:
        expected = 1 if self.gate == "requirements" else 2
        if len(self.artifacts) != expected:
            raise ValueError(f"Gate {self.gate} yêu cầu đúng {expected} artifact.")
        ids = {a.artifact_id for a in self.artifacts}
        if len(ids) != len(self.artifacts):
            raise ValueError("Danh sách artifact trong cổng duyệt không được trùng nhau.")
        if self.decision == "request_changes" and not self.comment.strip():
            raise ValueError("Bắt buộc nhập comment khi chọn request_changes.")
        return self


class ClarificationAnswer(StrictModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)

    @model_validator(mode="after")
    def non_blank(self) -> ClarificationAnswer:
        if not self.question_id.strip() or not self.answer.strip():
            raise ValueError("question_id và answer không được để trống.")
        return self


class ClarificationRequest(StrictModel):
    artifact: ArtifactRefInput
    answers: list[ClarificationAnswer] = Field(min_length=1)


class FinalAcceptanceRequest(StrictModel):
    manifest: ArtifactRefInput
    decision: Literal["accept", "request_changes"]
    comment: str = ""

    @model_validator(mode="after")
    def check_comment(self) -> FinalAcceptanceRequest:
        if self.decision == "request_changes" and not self.comment.strip():
            raise ValueError("Bắt buộc nhập comment khi từ chối nghiệm thu cuối.")
        return self


def _iso_timestamp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "1970-01-01T00:00:00Z"
    if "T" in text:
        return text if text.endswith("Z") or "+" in text else text + "Z"
    return text.replace(" ", "T", 1) + "Z"


def _media_type(kind: str, content: str) -> str:
    if kind in JSON_ARTIFACT_KINDS:
        return "application/json"
    if kind == "requirements_markdown":
        return "text/markdown"
    if kind == "patch":
        return "text/x-diff"
    if kind == "document":
        stripped = content.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(content)
                return "application/json"
            except json.JSONDecodeError:
                pass
    return "text/plain"


def _event_message(event_type: str, payload: dict) -> str:
    if not payload:
        return event_type
    for key in ("message", "reason", "status", "gate", "decision", "tool", "target_role", "code"):
        if key in payload and payload[key] is not None:
            return f"{event_type}: {payload[key]}"
    return event_type


def _extract_last_error(run_row: dict, events: list[dict]) -> dict | None:
    status = run_row["status"]
    budget = json.loads(run_row["budget_json"] or "{}")
    stop_reason = budget.get("stop_reason")
    if stop_reason in {
        "token_limit_exceeded",
        "cost_limit_exceeded",
        "tool_call_limit_exceeded",
        "tool_limit_exceeded",
        "time_limit_exceeded",
    }:
        return {"code": "budget_exceeded", "message": f"Run dừng do vượt hạn mức ({stop_reason})."}
    for row in reversed(events):
        etype = row["event_type"]
        payload = json.loads(row["payload_json"] or "{}")
        if etype in {"quota_exceeded", "budget.exceeded"}:
            return {"code": "budget_exceeded", "message": "Run đã chạm ngưỡng hạn mức được cấp."}
        if etype == "tool.denied":
            tool = payload.get("tool", "unknown")
            return {"code": "tool_denied", "message": f"Công cụ bị chặn bởi Gateway ({tool})."}
        if etype in {"handoff.rejected", "invalid_handoff"} and status in {"needs_human_review", "failed"}:
            return {"code": "invalid_request", "message": f"Đầu ra agent không hợp lệ ({payload.get('reason', etype)})."}
    if status in {"needs_human_review", "failed"}:
        return {"code": "invalid_transition", "message": f"Run đang ở trạng thái {status}, cần kiểm tra."}
    return None


def _compute_quota(run_row: dict, steps: list[dict], tool_calls: list[dict]) -> dict:
    budget = json.loads(run_row["budget_json"] or "{}")
    source = budget.get("usage") if isinstance(budget.get("usage"), dict) else budget
    if isinstance(source, dict) and {"input_tokens", "output_tokens", "usage_complete", "tool_calls"} <= source.keys():
        return {
            "input_tokens": max(0, int(source["input_tokens"] or 0)),
            "output_tokens": max(0, int(source["output_tokens"] or 0)),
            "usage_complete": bool(source["usage_complete"]),
            "tool_calls": max(0, int(source["tool_calls"] or 0)),
        }
    input_tokens = 0
    output_tokens = 0
    usage_complete = True
    for step in steps:
        if step["status"] == "started":
            continue
        raw = json.loads(step["usage_json"] or "{}")
        if not raw:
            continue
        inp = raw.get("input_tokens")
        out = raw.get("output_tokens")
        if isinstance(inp, int) and inp >= 0:
            input_tokens += inp
        if isinstance(out, int) and out >= 0:
            output_tokens += out
        if raw.get("usage_complete") is False or inp is None or out is None:
            usage_complete = False
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage_complete": usage_complete,
        "tool_calls": len(tool_calls),
    }


def _next_actions(status: str, checkpoint: dict) -> list[str]:
    if status in {"queued", "running"}:
        return ["cancel", "inspect"]
    if status == "waiting_approval":
        if checkpoint.get("pending_questions"):
            return ["clarify", "cancel", "inspect"]
        return ["review", "cancel", "inspect"]
    if status in {"pending_recovery", "needs_human_review"}:
        return ["resume", "cancel", "inspect"]
    if status == "completed":
        if checkpoint.get("final_acceptance", {}).get("decision") == "accept":
            return ["inspect"]
        return ["accept_output", "inspect"]
    return ["inspect"]


def create_app(
    database: Database,
    workspace_root: Path | str,
    *,
    on_cancel: Callable[[str, str], None] | None = None,
    export_secrets: tuple[str, ...] = (),
) -> FastAPI:
    """Build the FastAPI application bound to one local SQLite DB and workspace root."""
    root = Path(workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    database.migrate()

    store = ArtifactStore(root, database)
    queue = Queue(database)
    approvals = ApprovalService(database)
    audit = TraceAuditService(database)
    recovery = RecoveryService(database, store)

    app = FastAPI(
        title="Chuyên đề KTPM – API cục bộ",
        version="0.1.0",
        description="Local loopback platform API implementing D10.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _brief_dir() -> Path:
        folder = root / "_briefs"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _read_project_payload(row: dict) -> dict:
        brief = row["brief_uri"]
        constraints: list[str] = []
        candidate = (root / brief).resolve()
        try:
            if candidate.is_relative_to(root) and candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("brief"), str):
                    brief = data["brief"]
                    if isinstance(data.get("constraints"), list):
                        constraints = [str(c) for c in data["constraints"]]
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return {
            "project_id": row["id"],
            "name": row["name"],
            "brief": brief,
            "constraints": constraints,
        }

    def _find_run(run_id: str) -> dict:
        with database.transaction() as repo:
            row = repo._db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "Không tìm thấy run trong dự án cục bộ.")
        return dict(row)

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = exc.errors()[0].get("msg", "Dữ liệu không hợp lệ.") if exc.errors() else "Dữ liệu không hợp lệ."
        return JSONResponse(status_code=422, content={"code": "invalid_request", "message": str(detail)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/projects")
    def list_projects() -> list[dict]:
        with database.transaction() as repo:
            rows = [dict(r) for r in repo._db.execute("SELECT * FROM projects ORDER BY created_at DESC, rowid DESC")]
        return [_read_project_payload(row) for row in rows]

    @app.post("/projects", status_code=201)
    def create_project(body: CreateProjectRequest) -> dict:
        brief_rel = f"_briefs/{new_id()}.json"
        brief_path = _brief_dir() / Path(brief_rel).name
        brief_path.write_text(
            json.dumps({"brief": body.brief, "constraints": body.constraints}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with database.transaction(write=True) as repo:
            project_id = repo.create_project(body.name.strip(), brief_rel)
            row = repo.get_project(project_id)
        return _read_project_payload(row)

    @app.get("/projects/{project_id}/runs")
    def list_runs(project_id: str) -> list[dict]:
        with database.transaction() as repo:
            try:
                repo.get_project(project_id)
            except KeyError as exc:
                raise ApiError(404, "not_found", "Không tìm thấy dự án.") from exc
            rows = repo._db.execute(
                "SELECT id, project_id, status FROM runs WHERE project_id=? ORDER BY created_at DESC, rowid DESC",
                (project_id,),
            ).fetchall()
        return [{"project_id": r["project_id"], "run_id": r["id"], "status": r["status"]} for r in rows]

    @app.post("/projects/{project_id}/runs", status_code=202)
    def create_run(project_id: str, body: CreateRunRequest) -> dict:
        with database.transaction() as repo:
            try:
                repo.get_project(project_id)
            except KeyError as exc:
                raise ApiError(404, "not_found", "Không tìm thấy dự án.") from exc
        config = {"configuration_ref": body.configuration_ref} if body.configuration_ref else {}
        try:
            run_id = queue.enqueue(project_id, body.idempotency_key.strip(), config, {})
        except StorageConflict as exc:
            raise ApiError(409, "idempotency_conflict", "Khóa trước đó thuộc một payload khác.") from exc
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        with database.transaction() as repo:
            run_row = repo.get_run(project_id, run_id)
        return {"project_id": project_id, "run_id": run_id, "status": run_row["status"]}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        with database.transaction() as repo:
            reader = repo.for_run(project_id, run_id)
            steps = reader.records("agent_steps")
            tool_calls = reader.records("tool_calls")
            events = sorted(reader.records("events"), key=lambda e: e["id"])
        checkpoint = json.loads(run_row["checkpoint_json"] or "{}")
        active_step = next((s["id"] for s in reversed(steps) if s["status"] == "started"), None)
        current_step_id = active_step or (steps[-1]["id"] if steps else None)
        pending_gate = checkpoint.get("pending_gate") or {}
        gate_artifact_ids = [
            item["artifact_id"]
            for item in pending_gate.get("artifacts", [])
            if isinstance(item, dict) and item.get("artifact_id")
        ]
        question_artifact_id = (
            gate_artifact_ids[0]
            if checkpoint.get("pending_questions") and gate_artifact_ids
            else None
        )
        return {
            "project_id": project_id,
            "run_id": run_id,
            "status": run_row["status"],
            "stage": run_row["stage"],
            "current_step_id": current_step_id,
            "quota": _compute_quota(run_row, steps, tool_calls),
            "next_actions": _next_actions(run_row["status"], checkpoint),
            "last_error": _extract_last_error(run_row, events),
            "gate_artifact_ids": gate_artifact_ids,
            "question_artifact_id": question_artifact_id,
        }

    @app.get("/runs/{run_id}/events")
    def get_events(
        run_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        page = audit.poll_events(project_id, run_id, after=after, limit=limit)
        with database.transaction() as repo:
            steps_by_id = {s["id"]: s for s in repo.for_run(project_id, run_id).records("agent_steps")}
        items = []
        for item in page["items"]:
            step_id = item["step_id"]
            payload = item["payload"] if isinstance(item["payload"], dict) else {}
            role = steps_by_id[step_id]["agent_role"] if step_id in steps_by_id else payload.get("role")
            items.append({
                "sequence": item["sequence"],
                "kind": item["event_type"],
                "role": str(role) if role is not None else None,
                "message": _event_message(item["event_type"], payload),
                "step_id": step_id,
                "created_at": _iso_timestamp(item["created_at"]),
            })
        return {"items": items, "next_cursor": page["next_cursor"]}

    def _previous_map(artifacts: list[dict]) -> dict[str, str | None]:
        by_type_ver = {(a["type"], a["version"]): a["id"] for a in artifacts}
        return {
            a["id"]: by_type_ver.get((a["type"], a["version"] - 1)) if a["version"] > 1 else None
            for a in artifacts
        }

    @app.get("/runs/{run_id}/artifacts")
    def list_artifacts(run_id: str, kind: str | None = Query(default=None)) -> list[dict]:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        with database.transaction() as repo:
            all_rows = repo.for_run(project_id, run_id).records("artifacts")
        prev_ids = _previous_map(all_rows)
        rows = [r for r in all_rows if kind is None or r["type"] == kind]
        rows.sort(key=lambda r: (r["type"], r["version"], r["id"]))
        return [
            {
                "run_id": run_id,
                "artifact_id": r["id"],
                "kind": r["type"],
                "version": r["version"],
                "sha256": r["sha256"],
                "previous_artifact_id": prev_ids[r["id"]],
            }
            for r in rows
        ]

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str, run_id: str = Query(min_length=1)) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        with database.transaction() as repo:
            all_rows = repo.for_run(project_id, run_id).records("artifacts")
        row = next((r for r in all_rows if r["id"] == artifact_id), None)
        if row is None:
            raise ApiError(404, "not_found", "Không tìm thấy artifact trong phạm vi run hiện tại.")
        prev_ids = _previous_map(all_rows)
        try:
            content = store.read(project_id, run_id, row["id"], row["version"], row["sha256"]).decode("utf-8")
        except (KeyError, FileNotFoundError, StorageConflict) as exc:
            raise ApiError(404, "not_found", "Nội dung artifact không tồn tại hoặc không khớp chữ ký.") from exc
        return {
            "run_id": run_id,
            "artifact_id": row["id"],
            "kind": row["type"],
            "version": row["version"],
            "sha256": row["sha256"],
            "previous_artifact_id": prev_ids[row["id"]],
            "media_type": _media_type(row["type"], content),
            "content": content,
        }

    @app.post("/runs/{run_id}/approvals")
    def review_gate(run_id: str, body: ApprovalRequest) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        refs = [
            ContractArtifactRef(run_id=run_id, artifact_id=item.artifact_id, version=item.version, sha256=item.sha256)
            for item in body.artifacts
        ]
        try:
            result = approvals.decide_gate(project_id, run_id, body.gate, refs, body.decision, body.comment)
        except ApprovalVersionConflict as exc:
            raise ApiError(409, "approval_version_conflict", "Tải lại phiên bản mới trước khi duyệt.") from exc
        except InvalidGateTransition as exc:
            raise ApiError(409, "invalid_transition", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        return {
            "run_id": run_id,
            "decision_id": result.approval_ids[0],
            "status": result.next_status,
        }

    @app.post("/runs/{run_id}/clarifications")
    def answer_questions(run_id: str, body: ClarificationRequest) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        if run_row["status"] != RunState.WAITING.value:
            raise ApiError(409, "invalid_transition", "Run chưa ở trạng thái chờ làm rõ yêu cầu.")
        ref = ContractArtifactRef(
            run_id=run_id,
            artifact_id=body.artifact.artifact_id,
            version=body.artifact.version,
            sha256=body.artifact.sha256,
        )
        try:
            approvals.record_clarification(
                project_id, run_id, ref, [a.model_dump() for a in body.answers],
            )
        except ApprovalVersionConflict as exc:
            raise ApiError(409, "approval_version_conflict", "Tải lại phiên bản mới trước khi trả lời.") from exc
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        updated = _find_run(run_id)
        return {
            "run_id": run_id,
            "decision_id": new_id(),
            "status": updated["status"],
        }

    @app.post("/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        if run_row["status"] in {RunState.COMPLETED.value, RunState.FAILED.value, RunState.CANCELLED.value}:
            raise ApiError(409, "invalid_transition", "Run chưa ở trạng thái cho phép hủy.")
        try:
            outcome = recovery.cancel(project_id, run_id, wait_seconds=1)
        except StorageConflict as exc:
            raise ApiError(409, "invalid_transition", str(exc)) from exc
        if on_cancel is not None:
            on_cancel(project_id, run_id)
        return {"project_id": project_id, "run_id": run_id, "status": outcome["status"]}

    @app.post("/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        try:
            outcome = recovery.resume(project_id, run_id)
        except StorageConflict as exc:
            raise ApiError(409, "invalid_transition", "Run chưa ở trạng thái cho phép khôi phục.") from exc
        if outcome["status"] != RunState.QUEUED.value:
            raise ApiError(409, "invalid_transition", f"Không thể khôi phục: {outcome['reason']}.")
        return {"project_id": project_id, "run_id": run_id, "status": outcome["status"]}

    @app.get("/runs/{run_id}/tasks")
    def get_tasks(run_id: str) -> list[dict]:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        with database.transaction() as repo:
            reader = repo.for_run(project_id, run_id)
            tasks = reader.records("tasks")
            deps = reader.records("task_dependencies")
            traces = reader.records("trace_links")
        deps_by_task: dict[str, list[str]] = {}
        for dep in deps:
            deps_by_task.setdefault(dep["task_id"], []).append(dep["depends_on_task_id"])
        patches_by_task: dict[str, list[str]] = {}
        for ln in traces:
            if ln["source_type"] == "task" and ln["target_type"] in {"patch", "artifact"}:
                patches_by_task.setdefault(ln["source_id"], []).append(ln["target_id"])
        return [
            {
                "task_id": t["id"],
                "title": t["description"],
                "status": t["status"],
                "requirement_ids": json.loads(t["requirement_refs_json"]),
                "dependency_ids": sorted(set(deps_by_task.get(t["id"], []))),
                "patch_artifact_ids": sorted(set(patches_by_task.get(t["id"], []))),
            }
            for t in tasks
        ]

    @app.get("/runs/{run_id}/test-reports")
    def get_test_reports(run_id: str) -> list[dict]:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        with database.transaction() as repo:
            reader = repo.for_run(project_id, run_id)
            reports = reader.records("test_reports")
            artifacts = reader.records("artifacts")
            traces = reader.records("trace_links")

        runner_by_commit: dict[tuple[str | None, str], str] = {}
        bugs_by_task_commit: dict[tuple[str | None, str], list[str]] = {}
        for art in artifacts:
            if art["type"] == "test_report":
                try:
                    data = json.loads(store.read(project_id, run_id, art["id"], art["version"], art["sha256"]))
                    ref = data.get("runner_output") or {}
                    if ref.get("artifact_id"):
                        runner_by_commit[(data.get("task_id"), data.get("commit", ""))] = ref["artifact_id"]
                except (OSError, json.JSONDecodeError, StorageConflict, KeyError):
                    pass
            elif art["type"] == "bug_report":
                try:
                    data = json.loads(store.read(project_id, run_id, art["id"], art["version"], art["sha256"]))
                    bugs_by_task_commit.setdefault(
                        (data.get("task_id"), data.get("commit", "")), []
                    ).append(art["id"])
                except (OSError, json.JSONDecodeError, StorageConflict, KeyError):
                    pass

        traces_by_report: dict[str, list[str]] = {}
        for ln in traces:
            if ln["target_type"] in {"test", "report"}:
                traces_by_report.setdefault(ln["target_id"], []).append(ln["source_id"])

        return [
            {
                "report_id": r["id"],
                "task_id": r["task_id"],
                "suite_id": r["suite_id"],
                "commit": r["commit_hash"],
                "exit_code": r["exit_code"],
                "passed": r["passed"],
                "failed": r["failed"],
                "skipped": r["skipped"],
                "errors": r["errors"],
                "log_artifact_id": runner_by_commit.get((r["task_id"], r["commit_hash"])),
                "bug_artifact_ids": sorted(set(bugs_by_task_commit.get((r["task_id"], r["commit_hash"]), []))),
                "trace_artifact_ids": sorted(set(traces_by_report.get(r["id"], []))),
            }
            for r in reports
        ]

    @app.get("/runs/{run_id}/export")
    def export_run(run_id: str) -> Response:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        ws = Workspace(root, project_id, run_id)
        if not (ws.path / ".git").exists():
            raise ApiError(409, "invalid_transition", "Run chưa có commit mã nguồn để đóng gói xuất.")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_zip = Path(tmp) / f"run-{run_id}.zip"
                result = build_export_zip(
                    database, store, root, project_id, run_id, out_zip, secrets=export_secrets,
                )
                payload = out_zip.read_bytes()
        except (SecretLeakError, ExportPathError) as exc:
            raise ApiError(409, "tool_denied", str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ApiError(409, "invalid_transition", str(exc)) from exc
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="run-{run_id}.zip"',
                "X-Export-Manifest-SHA256": result.manifest_sha256,
            },
        )

    @app.post("/runs/{run_id}/acceptance")
    def review_output(run_id: str, body: FinalAcceptanceRequest) -> dict:
        run_row = _find_run(run_id)
        project_id = run_row["project_id"]
        if run_row["status"] not in {RunState.COMPLETED.value, RunState.REVIEW.value}:
            raise ApiError(409, "invalid_transition", "Chỉ ghi nhận nghiệm thu cuối khi run đã hoàn tất hoặc chờ soát.")
        with database.transaction(write=True) as repo:
            reader = repo.for_run(project_id, run_id)
            try:
                art = reader.artifact(body.manifest.artifact_id, body.manifest.version)
            except KeyError as exc:
                raise ApiError(409, "approval_version_conflict", "Không tìm thấy phiên bản manifest này trong run.") from exc
            if art["sha256"] != body.manifest.sha256 or reader.latest_version(art["type"]) != body.manifest.version:
                raise ApiError(409, "approval_version_conflict", "Tải lại phiên bản manifest mới nhất trước khi xác nhận.")
            decision_id = new_id()
            repo._db.execute(
                "INSERT INTO approvals(id,run_id,artifact_id,artifact_version,artifact_sha256,decision,comment) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    decision_id,
                    run_id,
                    body.manifest.artifact_id,
                    body.manifest.version,
                    body.manifest.sha256,
                    body.decision,
                    body.comment,
                ),
            )
            checkpoint = json.loads(run_row["checkpoint_json"] or "{}")
            checkpoint["final_acceptance"] = {
                "decision_id": decision_id,
                "decision": body.decision,
                "comment": body.comment,
                "manifest": body.manifest.model_dump(),
            }
            repo._db.execute("UPDATE runs SET checkpoint_json=? WHERE id=?", (encode(checkpoint), run_id))
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, ?, ?)",
                (
                    run_id,
                    "acceptance.recorded",
                    encode({"decision_id": decision_id, "decision": body.decision, "artifact_id": body.manifest.artifact_id}),
                ),
            )
        return {"run_id": run_id, "decision_id": decision_id, "status": run_row["status"]}

    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    index_file = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    if index_file.is_file():
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def serve_ui_index() -> FileResponse:
            return FileResponse(index_file)

    return app


def serve_local(
    database_path: Path | str,
    workspace_root: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the platform API strictly on a loopback interface."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"Local platform API must bind to loopback only, refused host={host!r}")
    import uvicorn

    app = create_app(Database(database_path), workspace_root)
    uvicorn.run(app, host=host, port=port)
