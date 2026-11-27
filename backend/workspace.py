"""Run-scoped Git checkpoints. Only the trusted host creates a Workspace."""

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4


def _reserved(name):
    return name.partition(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
        *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
    }


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
        raise ValueError("invalid workspace identifier")
    if _reserved(value):
        raise ValueError("reserved workspace identifier")
    return value


def _check_node(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("linked paths are forbidden")
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError("hard-linked files are forbidden")


def content_hash(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Edit:
    path: str
    expected_hash: str | None
    text: str | None


class PendingRecovery(RuntimeError):
    pass


class Workspace:
    def __init__(self, root, project_id, run_id, *, file_limit=256*1024, patch_limit=1024*1024,
                 count_limit=64):
        self.root = Path(root).resolve()
        project = self.root / _id(project_id)
        self.path = project / _id(run_id)
        for entry in (project, self.path):
            _check_node(entry)
        self.file_limit, self.patch_limit, self.count_limit = file_limit, patch_limit, count_limit

    def git(self, *args):
        env = {k: v for k, v in os.environ.items()
               if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "COMSPEC"}}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
                   GIT_LITERAL_PATHSPECS="1", GIT_CEILING_DIRECTORIES=str(self.path.parent))
        command = ["git", "--no-pager", "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false",
                   "-c", "core.hooksPath=" + str(self.path / ".git" / "unused-hooks"),
                   "-c", "commit.gpgSign=false", "-c", "user.name=SDLC Host",
                   "-c", "user.email=host@localhost", *args]
        return subprocess.run(command, cwd=self.path, env=env, check=True, capture_output=True,
                              timeout=30).stdout.decode("utf-8")

    def initialize(self):
        self.path.mkdir(parents=True, exist_ok=True)
        for name in ("app", "tests_dev", "artifacts", "logs", ".git"):
            _check_node(self.path / name)
        for name in ("app", "tests_dev", "artifacts", "logs"):
            (self.path / name).mkdir(exist_ok=True)
        if not (self.path / ".git").exists():
            self.git("init", "-q", "-b", "main")
            self.git("commit", "--allow-empty", "-qm", "Initialize run")
        return self.head()

    def head(self):
        return self.git("rev-parse", "--verify", "HEAD").strip()

    def _file(self, name):
        if not isinstance(name, str) or len(name) > 512 or "\\" in name or ":" in name:
            raise ValueError("invalid workspace path")
        parts = name.split("/")
        if len(parts) < 2 or parts[0] not in ("app", "tests_dev"):
            raise ValueError("file outside app and tests_dev")
        current = self.path
        for part in parts:
            if (not re.fullmatch(r"[A-Za-z0-9_.@-]+", part) or part in {".", ".."}
                    or part.endswith(".") or part.lower().startswith((".git", ".env"))
                    or _reserved(part)):
                raise ValueError("invalid workspace path component")
            current = current / part
            _check_node(current)
        return current

    def read(self, name):
        path = self._file(name)
        with path.open("rb") as f:
            data = f.read(self.file_limit + 1)
        if len(data) > self.file_limit:
            raise ValueError("file exceeds read limit")
        return data

    def status(self):
        return self.git("status", "--porcelain", "--", "app", "tests_dev")

    def diff(self, before, after):
        for commit in (before, after):
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
                raise ValueError("expected full Git commit id")
        return self.git("diff", "--no-ext-diff", "--no-textconv", before, after, "--", "app", "tests_dev")

    def operation_receipt(self, operation_id):
        _id(operation_id)
        path = self.path / "logs" / f"op-{operation_id}.json"
        _check_node(path)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def apply(self, task_id, input_commit, edits, *, operation_id=None):
        _id(task_id)
        if operation_id is not None:
            _id(operation_id)
        if not edits or len(edits) > self.count_limit:
            raise ValueError("invalid number of patch files")
        patch_id = uuid4().hex
        journal = self.path / "logs" / "pending-patch.json"
        try:
            lock = journal.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise PendingRecovery("workspace operation in progress or pending recovery") from exc
        effects_started = False
        committed = False
        try:
            with lock:
                if input_commit != self.head() or self.status():
                    raise ValueError("stale commit or dirty workspace")
                patch = []
                seen = set()
                byte_count = 0
                for edit in edits:
                    path = self._file(edit.path)
                    identity = edit.path.casefold()
                    if identity in seen:
                        raise ValueError("duplicate path")
                    seen.add(identity)
                    if path.exists() and not path.is_file():
                        raise ValueError("expected file")
                    current = self.read(edit.path) if path.exists() else None
                    actual = content_hash(current) if current is not None else None
                    if actual != edit.expected_hash:
                        raise ValueError("stale file hash")
                    data = None if edit.text is None else edit.text.encode("utf-8")
                    if data == current:
                        raise ValueError("edit changes nothing")
                    byte_count += len(data or b"") + len(current or b"")
                    if len(data or b"") > self.file_limit or byte_count > self.patch_limit:
                        raise ValueError("patch exceeds size limit")
                    patch.append((path, data))
                names = sorted(seen)
                if any(b.startswith(a + "/") for a in names for b in names):
                    raise ValueError("file and directory paths overlap")
                canonical = json.dumps([asdict(e) for e in edits], ensure_ascii=False,
                                       sort_keys=True, separators=(",", ":")).encode()
                receipt = dict(patch_id=patch_id, task_id=task_id, input_commit=input_commit,
                               patch_hash=content_hash(canonical))
                if operation_id is not None:
                    receipt["operation_id"] = operation_id
                json.dump(receipt, lock)
                lock.flush()
                os.fsync(lock.fileno())
            effects_started = True
            for path, data in patch:
                if data is None:
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            self.git("add", "-A", "--", *(e.path for e in edits))
            self.git("commit", "-qm", f"{task_id}: {patch_id} {receipt['patch_hash']}")
            receipt["output_commit"] = self.head()
            receipt["diff"] = self.diff(input_commit, receipt["output_commit"])
            with (self.path / "logs" / (patch_id + ".json")).open("x", encoding="utf-8") as f:
                json.dump(receipt, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if operation_id is not None:
                op_file = self.path / "logs" / f"op-{operation_id}.json"
                with op_file.open("x", encoding="utf-8") as f:
                    json.dump(receipt, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
            committed = True
            return receipt
        finally:
            if not effects_started or committed:
                journal.unlink(missing_ok=True)
