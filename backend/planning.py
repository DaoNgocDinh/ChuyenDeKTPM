"""Plan checks and review rendering used before the host opens the architecture-and-plan gate."""

from graphlib import TopologicalSorter
from pathlib import PurePosixPath, PureWindowsPath

from .contracts import check_handoff


def task_order(plan):
    graph = TopologicalSorter({task.task_id: task.dependencies for task in plan.tasks})
    graph.prepare()
    order = []
    while graph.is_active():
        ready = sorted(graph.get_ready())
        order.extend(ready)
        graph.done(*ready)
    return order


def validate_plan(plan, requirements, architecture, requirements_ref, architecture_ref):
    check_handoff(requirements, architecture, plan, requirements_ref, architecture_ref)
    fr_ids = {item.id for item in requirements.functional}
    for task in plan.tasks:
        if not fr_ids.intersection(task.requirement_ids):
            raise ValueError("Every task must implement a functional requirement")
        if len(task.files) != len(set(task.files)):
            raise ValueError("Duplicate planned file path in task")
        for filename in task.files:
            parts = PurePosixPath(filename).parts
            if (len(parts) < 2 or parts[0] != "app" or ".." in parts or "\\" in filename
                    or ":" in filename or PureWindowsPath(filename).drive):
                raise ValueError("Planned code paths must stay below app/")
    return task_order(plan)


def render_plan(plan, execution_order=None) -> str:
    order = execution_order if execution_order is not None else task_order(plan)
    by_id = {task.task_id: task for task in plan.tasks}
    parts = [
        "# Kế hoạch thực thi (Task DAG)",
        "",
        "## Thứ tự thực hiện",
        "",
        " -> ".join(order),
    ]
    for tid in order:
        task = by_id[tid]
        deps = ", ".join(task.dependencies) if task.dependencies else "Không có"
        parts.extend([
            "",
            f"## {task.task_id}",
            "",
            f"- **FR áp dụng:** {', '.join(task.requirement_ids)}",
            f"- **Phụ thuộc:** {deps}",
            f"- **Tệp dự kiến:** {', '.join(task.files)}",
            f"- **Kiểm thử cần chạy:** {', '.join(task.tests)}",
            "- **Điều kiện hoàn thành:**",
        ])
        parts.extend(f"  - {cond}" for cond in task.done_conditions)
    return "\n".join(parts) + "\n"
