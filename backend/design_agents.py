"""Model-backed SDLC roles. The trusted host owns artifacts and approval gates."""

import json

from pydantic import ValidationError

from .approvals import ApprovalService
from .architecture_view import render_architecture, validate_architecture
from .contracts import Architecture, Plan, Requirements
from .llm import ModelError, invoke
from .planning import render_plan, validate_plan


def render_requirements(requirements: Requirements) -> str:
    sections = ["# Yêu cầu", "", "## Tác nhân", ""]
    sections.extend(f"- {actor}" for actor in requirements.actors)
    for heading, items in (("Yêu cầu chức năng", requirements.functional),
                           ("Yêu cầu phi chức năng", requirements.nonfunctional)):
        if items:
            sections.extend(["", f"## {heading}"])
        for item in items:
            sections.extend(["", f"### {item.id}", "", item.description, ""])
            sections.extend(f"- {criterion}" for criterion in item.acceptance)
    for title, values in (("Giả định", requirements.assumptions), ("Cần làm rõ", requirements.questions)):
        if values:
            sections.extend(["", f"## {title}", ""])
            sections.extend(f"- {value}" for value in values)
    return "\n".join(sections) + "\n"


def aggregate_usage(attempts):
    summary = {"attempts": attempts, "usage_complete": all(
        {"input_tokens", "output_tokens"} <= item.keys() for item in attempts
    )}
    for name in ("input_tokens", "output_tokens", "cache_read_tokens", "thinking_tokens", "total_tokens"):
        values = [item[name] for item in attempts if name in item]
        if values:
            summary[name] = sum(values)
    if "cache_read_tokens" in summary:
        summary["cached_tokens"] = summary["cache_read_tokens"]
    return summary


class DesignAgents:
    def __init__(self, store, skills, model=invoke):
        self.store = store
        self.skills = skills
        self.model = model

    def _generate(self, role, instructions, facts, schema, validate=None, bound=None, *, allow_blocker=False):
        bound = bound or {}
        output_schema = schema.model_json_schema()
        for field in bound:
            del output_schema["properties"][field]
            output_schema["required"].remove(field)
        if allow_blocker:
            arch_schema = output_schema
            defs = arch_schema.pop("$defs", None)
            arch_schema["properties"]["blocker"] = {"type": "null"}
            blocker_schema = {
                "type": "object",
                "properties": {"blocker": {"type": "string", "minLength": 1}},
                "required": ["blocker"],
                "additionalProperties": False,
            }
            output_schema = {"anyOf": [arch_schema, blocker_schema]}
            if defs:
                output_schema["$defs"] = defs
        prompt = (
            f"Vai trò {role}. {instructions}\n"
            + self.skills.context(role)
            + "\nDữ liệu công việc do host cấp:\n" + json.dumps(facts, ensure_ascii=False)
        )
        attempts = []
        for attempt in range(2):
            try:
                reply = self.model(prompt, output_schema)
            except ModelError as error:
                attempts.append(error.usage)
                if attempt or error.code not in {"schema_invalid", "missing_structured_output"}:
                    error.usage = aggregate_usage(attempts)
                    raise
                prompt += "\nSửa dạng trả về thành một giá trị JSON đáp ứng đầy đủ schema."
                continue
            attempts.append({
                **reply.usage, "prompt_sha256": reply.prompt_sha256,
                "config_sha256": reply.config_sha256, "model": reply.model,
            })
            raw_output = dict(reply.output) if isinstance(reply.output, dict) else reply.output
            if allow_blocker and isinstance(raw_output, dict):
                blocker = raw_output.pop("blocker", None)
                if isinstance(blocker, str) and blocker.strip():
                    raise ModelError(f"{role.lower()}_blocked", aggregate_usage(attempts))
            try:
                data = schema.model_validate({**raw_output, **bound} if isinstance(raw_output, dict) else raw_output)
                if validate:
                    validate(data)
            except (ValidationError, ValueError) as error:
                if attempt:
                    raise ModelError("invalid_handoff", aggregate_usage(attempts)) from None
                reason = error.errors(include_input=False)[0]["msg"] if isinstance(error, ValidationError) else str(error)
                prompt += "\nLỗi dữ liệu cần sửa: " + reason
                continue
            return data, aggregate_usage(attempts)

    def _read_input(self, order, ref, kind, schema):
        if ref.run_id != order.run_id:
            raise ValueError("Artifact belongs to another run")
        with self.store.database.transaction() as repo:
            reader = repo.for_run(order.project_id, order.run_id)
            row = reader.artifact(ref.artifact_id, ref.version)
            if row["type"] != kind or reader.latest_version(kind) != ref.version:
                raise ValueError("Unexpected or stale input artifact")
        raw = self.store.read(order.project_id, order.run_id, ref.artifact_id, ref.version, ref.sha256)
        return schema.model_validate_json(raw)

    def dispatch(self, order):
        from .orchestrator import RoleOutput

        if order.role == "Architecture":
            return self._architecture(order)
        if order.role == "Planning":
            return self._planning(order)
        if order.role != "Requirement":
            raise ValueError(f"Unsupported design role: {order.role}")
        config = order.context.get("config", {})
        project = order.context.get("project", {})
        brief = config.get("brief") or order.context.get("brief") or project.get("brief_uri")
        if not isinstance(brief, str) or not brief.strip():
            raise ValueError("Missing project brief")
        facts = {"brief": brief, "constraints": config.get("constraints", []),
                 "feedback": order.context.get("feedback", [])}
        if order.inputs:
            if len(order.inputs) != 1:
                raise ValueError("Expected one previous requirements version")
            facts["previous"] = self._read_input(order, order.inputs[0], "requirements", Requirements).model_dump()
        requirements, usage = self._generate(
            order.role, "Phân tích brief, nêu yêu cầu cùng tiêu chí kiểm tra bằng tiếng Việt. "
            "Giữ phạm vi đã giao. Nếu một quy tắc nghiệp vụ còn mơ hồ, hỏi người dùng qua questions. "
            "Mỗi trường hợp sử dụng nằm trong mô tả FR và tiêu chí của nó.", facts, Requirements,
        )
        return RoleOutput(payload=requirements, usage=usage, markdown=render_requirements(requirements))

    def _approved_requirements(self, order, ref):
        requirements = self._read_input(order, ref, "requirements", Requirements)
        gates = ApprovalService(self.store.database)
        if requirements.questions or not gates.is_gate_approved(
            order.project_id, order.run_id, "requirements", [ref]
        ):
            raise ValueError("Requirements need clarification or approval at gate 1")
        return requirements

    def _architecture(self, order):
        from .orchestrator import RoleOutput

        if len(order.inputs) != 1:
            raise ValueError("Architecture needs one approved requirements artifact")
        ref = order.inputs[0]
        requirements = self._approved_requirements(order, ref)
        facts = {"requirements": requirements.model_dump(), "stack": ["FastAPI", "React", "SQLite"],
                 "revision_feedback": order.context.get("feedback", [])}
        if order.context.get("routing_bug"):
            facts["routing_bug"] = order.context["routing_bug"]
        architecture, usage = self._generate(
            order.role, "Thiết kế trên stack cố định trong facts. Nêu tên từng công nghệ ở components. "
            "Mỗi api_contract có khóa 'METHOD /path' và giá trị là một CHUỖI JSON biểu diễn một "
            "OpenAPI operation gồm summary, responses (mã HTTP -> object có description), requestBody "
            "nếu cần, và parameters hợp lệ cho path. Nêu liên kết, khóa, validation ở entities. "
            "Mỗi FR phải ánh xạ đến ít nhất một tên trong components. Tham chiếu phiên bản do host gắn. "
            "Nếu có mâu thuẫn không thể đáp ứng trên stack này, trả nguyên nhân qua trường blocker "
            "để Orchestrator đưa về chủ dự án xử lý (đặt blocker là null khi khả thi).",
            facts, Architecture, lambda design: validate_architecture(design, requirements, ref),
            bound={"requirements": ref}, allow_blocker=True,
        )
        return RoleOutput(payload=architecture, usage=usage, markdown=render_architecture(architecture))

    def _planning(self, order):
        from .orchestrator import RoleOutput

        if len(order.inputs) != 2:
            raise ValueError("Planning needs approved requirements and architecture artifacts")
        req_ref, arch_ref = order.inputs
        requirements = self._approved_requirements(order, req_ref)
        architecture = self._read_input(order, arch_ref, "architecture", Architecture)
        if architecture.requirements != req_ref:
            raise ValueError("Architecture does not match approved requirements version")
        facts = {
            "requirements": requirements.model_dump(),
            "architecture": architecture.model_dump(),
            "stack": ["FastAPI", "React", "SQLite"],
            "revision_feedback": order.context.get("feedback", []),
        }
        if order.context.get("routing_bug"):
            facts["routing_bug"] = order.context["routing_bug"]
        execution_order = []

        def check(plan):
            execution_order.clear()
            execution_order.extend(validate_plan(plan, requirements, architecture, req_ref, arch_ref))

        plan, usage = self._generate(
            order.role,
            "Phân rã kiến trúc thành các task nhỏ có thứ tự phụ thuộc hợp lệ (DAG không chu trình). "
            "Mỗi task phải có task_id duy nhất, ít nhất một FR chức năng trong requirement_ids, "
            "dependencies chỉ trỏ tới task_id khác đã khai báo, danh sách files dự kiến chỉ nằm dưới app/, "
            "done_conditions cụ thể để nghiệm thu và danh sách tests cần chạy. Hợp tất cả task phải phủ "
            "100% FR trong requirements.functional. Tham chiếu phiên bản do host gắn.",
            facts, Plan, check, bound={"requirements": req_ref, "architecture": arch_ref},
        )
        return RoleOutput(payload=plan, usage=usage, markdown=render_plan(plan, execution_order))
