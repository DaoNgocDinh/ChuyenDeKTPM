"""Typed wire formats for the host and versioned SDLC artifacts (D07)."""

from graphlib import CycleError, TopologicalSorter
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Role = Literal["Orchestrator", "Requirement", "Architecture", "Planning", "Dev", "Tester"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ArtifactRef(Contract):
    run_id: Text
    artifact_id: Text
    version: int = Field(ge=1)
    sha256: Hash


class Envelope(Contract):
    message_id: Text
    run_id: Text
    from_role: Role
    to_role: Role
    kind: Text
    schema_version: Literal["1"]
    input_refs: list[ArtifactRef]
    output_refs: list[ArtifactRef]
    task_id: Text | None = None
    correlation_id: Text

    @model_validator(mode="after")
    def same_run(self) -> Self:
        if any(ref.run_id != self.run_id for ref in self.input_refs + self.output_refs):
            raise ValueError("artifact belongs to a different run")
        return self


class RequirementItem(Contract):
    id: Text
    description: Text
    acceptance: list[Text] = Field(min_length=1)


class Requirements(Contract):
    actors: list[Text] = Field(min_length=1)
    functional: list[RequirementItem] = Field(min_length=1)
    nonfunctional: list[RequirementItem]
    assumptions: list[Text]
    questions: list[Text]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [r.id for r in self.functional + self.nonfunctional]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement id")
        return self


class Architecture(Contract):
    requirements: ArtifactRef
    adr: list[Text] = Field(min_length=1)
    components: dict[Text, Text] = Field(min_length=1)
    entities: dict[Text, Text] = Field(min_length=1)
    api_contract: dict[Text, Text] = Field(min_length=1)
    frontend: Text
    test_strategy: Text
    fr_components: dict[Text, list[Text]]


class Task(Contract):
    task_id: Text
    requirement_ids: list[Text] = Field(min_length=1)
    dependencies: list[Text]
    files: list[Text] = Field(min_length=1)
    done_conditions: list[Text] = Field(min_length=1)
    tests: list[Text] = Field(min_length=1)


class Plan(Contract):
    requirements: ArtifactRef
    architecture: ArtifactRef
    tasks: list[Task] = Field(min_length=1)

    @model_validator(mode="after")
    def check_dag(self) -> Self:
        ids = {t.task_id for t in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("duplicate task id")
        graph = {t.task_id: t.dependencies for t in self.tasks}
        if any(len(deps) != len(set(deps)) or set(deps) - ids for deps in graph.values()):
            raise ValueError("duplicate or unknown dependency")
        try:
            tuple(TopologicalSorter(graph).static_order())
        except CycleError as exc:
            raise ValueError("task dependency cycle") from exc
        if self.requirements.run_id != self.architecture.run_id:
            raise ValueError("cross-run plan inputs")
        return self


def check_handoff(requirements: Requirements, architecture: Architecture, plan: Plan,
                  requirement_ref: ArtifactRef, architecture_ref: ArtifactRef) -> None:
    if architecture.requirements != requirement_ref or plan.requirements != requirement_ref or plan.architecture != architecture_ref:
        raise ValueError("stale artifact inputs")
    fr = {r.id for r in requirements.functional}
    if set(architecture.fr_components) != fr:
        raise ValueError("architecture must cover every functional requirement")
    for components in architecture.fr_components.values():
        if not components or set(components) - architecture.components.keys():
            raise ValueError("unresolved component")
    covered = {rid for task in plan.tasks for rid in task.requirement_ids}
    if not fr <= covered or covered - (fr | {r.id for r in requirements.nonfunctional}):
        raise ValueError("invalid requirement coverage")


class DevResult(Contract):
    task_id: Text
    input_commit: Commit
    output_commit: Commit
    patch_sha256: Hash
    changed_files: list[Text] = Field(min_length=1)
    summary: Text


class TestReport(Contract):
    task_id: Text
    commit: Commit
    suite_id: Text
    runner_output: ArtifactRef
    exit_code: int
    passed: int = Field(ge=0)
    failures: int = Field(ge=0)
    errors: int = Field(ge=0)
    skipped: int = Field(ge=0)

    @property
    def all_passed(self) -> bool:
        return self.exit_code == 0 and self.passed > 0 and not (self.errors or self.failures or self.skipped)


class BugReport(Contract):
    task_id: Text
    commit: Commit
    report: ArtifactRef
    requirement_ids: list[Text] = Field(min_length=1)
    reproduce: list[Text] = Field(min_length=1)
    expected: Text
    actual: Text
    category: Literal["code", "requirements", "design", "infrastructure"]
