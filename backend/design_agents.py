"""Model-backed SDLC roles. The trusted host owns artifacts and approval gates."""

import json

from pydantic import ValidationError

from .contracts import Requirements
from .llm import ModelError, invoke


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

    def _generate(self, role, instructions, facts, schema, validate=None):
        prompt = (
            f"Vai trò {role}. {instructions}\n"
            + self.skills.context(role)
            + "\nDữ liệu công việc do host cấp:\n" + json.dumps(facts, ensure_ascii=False)
        )
        attempts = []
        for attempt in range(2):
            try:
                reply = self.model(prompt, schema.model_json_schema())
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
            try:
                data = schema.model_validate(reply.output)
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
