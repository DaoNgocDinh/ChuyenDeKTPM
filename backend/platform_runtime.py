"""Unified local platform runtime wiring FastAPI (I22), Worker (I05/I20), Orchestrator (I06/I18), and all 6 agents."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from backend.api import LOOPBACK_HOSTS, create_app
from backend.artifacts import ArtifactStore
from backend.coding_agents import CodingAgents
from backend.design_agents import DesignAgents
from backend.llm import invoke as infer
from backend.mcp_tools import step_client
from backend.orchestrator import Orchestrator, RoleOutput
from backend.recovery import RecoveryService
from backend.skill_registry import RunSkills
from backend.storage import Database
from backend.worker import Queue, Worker


class PlatformDispatcher:
    """Routes WorkOrders from Orchestrator to the 6 host-verified roles."""

    def __init__(
        self,
        store: ArtifactStore,
        image: str | None,
        *,
        model=infer,
        skill_root: Path | str | None = None,
        client_factory=step_client,
    ) -> None:
        self.store = store
        self.image = image
        self.model = model
        self.skill_root = Path(skill_root or Path(__file__).resolve().parents[1] / "skills")
        self.coding = CodingAgents(
            store, image, model=model, skill_root=self.skill_root, client_factory=client_factory,
        )

    def _hydrate_brief_context(self, order):
        context = dict(order.context)
        config = dict(context.get("config") or {})
        project = context.get("project") or {}
        brief_uri = project.get("brief_uri")
        if not config.get("brief") and not context.get("brief") and isinstance(brief_uri, str):
            candidate = (self.store.root / brief_uri).resolve()
            try:
                if candidate.is_relative_to(self.store.root) and candidate.is_file():
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and isinstance(data.get("brief"), str):
                        config["brief"] = data["brief"]
                        if isinstance(data.get("constraints"), list) and "constraints" not in config:
                            config["constraints"] = [str(c) for c in data["constraints"]]
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        context["config"] = config
        return replace(order, context=context)

    def __call__(self, order) -> RoleOutput:
        if order.role == "Orchestrator":
            return RoleOutput(
                payload={"decision": "approve", "requested_role": order.context.get("expected_role")},
                usage={"input_tokens": 0, "output_tokens": 0, "usage_complete": True},
            )
        if order.role in {"Requirement", "Architecture", "Planning"}:
            enriched = self._hydrate_brief_context(order)
            run_dir = self.store.root / enriched.project_id / enriched.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            enabled = enriched.context.get("config", {}).get("skills_enabled", True)
            skills = RunSkills(self.skill_root, enabled=enabled)
            skills.bind(run_dir / "skills.json")
            return DesignAgents(self.store, skills, model=self.model).dispatch(enriched)
        if order.role in {"Dev", "Tester"}:
            return self.coding(order)
        raise ValueError(f"Unsupported role: {order.role}")


@dataclass
class PlatformBundle:
    app: object
    worker: Worker
    orchestrator: Orchestrator
    recovery: RecoveryService
    database: Database
    store: ArtifactStore
    queue: Queue


def build_platform(
    database_path: Path | str,
    workspace_root: Path | str,
    *,
    image: str | None = None,
    model=infer,
    skill_root: Path | str | None = None,
    client_factory=step_client,
    final_check=None,
    lease_seconds: int = 30,
) -> PlatformBundle:
    """Assemble the complete local platform stack sharing one SQLite database and workspace root."""
    db = Database(database_path)
    db.migrate()
    root = Path(workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(root, db)
    queue = Queue(db)
    dispatcher = PlatformDispatcher(
        store,
        image if image is not None else os.getenv("KTPM_TEST_RUNNER_IMAGE"),
        model=model,
        skill_root=skill_root,
        client_factory=client_factory,
    )
    orchestrator = Orchestrator(queue, store, dispatcher, final_check or (lambda lease, refs: True))
    worker = Worker(queue, orchestrator, lease_seconds=lease_seconds)
    recovery = RecoveryService(db, store)
    app = create_app(db, root)
    return PlatformBundle(
        app=app, worker=worker, orchestrator=orchestrator, recovery=recovery,
        database=db, store=store, queue=queue,
    )


def run_local_platform(
    database_path: Path | str,
    workspace_root: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    image: str | None = None,
    poll_seconds: float = 0.5,
) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"Local platform must bind to loopback only, refused host={host!r}")
    import uvicorn

    bundle = build_platform(database_path, workspace_root, image=image)
    stop = threading.Event()
    worker_thread = threading.Thread(
        target=bundle.worker.run_forever,
        args=(stop,),
        kwargs={"poll_seconds": poll_seconds},
        daemon=True,
    )
    worker_thread.start()
    try:
        uvicorn.run(bundle.app, host=host, port=port)
    finally:
        stop.set()
        worker_thread.join(timeout=5)


def _ensure_local_docker_on_path() -> None:
    if shutil.which("docker") is not None or os.name != "nt":
        return
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop" / "resources" / "bin",
        Path(r"C:\Program Files\Docker\Docker\resources\bin"),
    ]
    for folder in candidates:
        if (folder / "docker.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return


def main() -> None:
    _ensure_local_docker_on_path()
    parser = argparse.ArgumentParser(description="Run local SDLC multi-agent platform (API + Worker).")
    parser.add_argument("--db", default="data/platform.sqlite", help="SQLite database path")
    parser.add_argument("--workspaces", default="data/workspaces", help="Workspace root directory")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback bind host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    parser.add_argument("--image", default=os.getenv("KTPM_TEST_RUNNER_IMAGE"), help="Docker runner image ID")
    args = parser.parse_args()
    print(f"Open Web UI at: http://{args.host}:{args.port}/")
    run_local_platform(args.db, args.workspaces, host=args.host, port=args.port, image=args.image)


if __name__ == "__main__":
    main()
