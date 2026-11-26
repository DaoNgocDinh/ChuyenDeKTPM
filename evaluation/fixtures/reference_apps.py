"""Local HTTP + SQLite reference servers for validating E01 positive/negative suites.

These fixtures exist strictly to verify that E01's 30 criteria pass on compliant
implementations and catch specific defects on broken implementations.
"""

from __future__ import annotations

import contextlib
import html
import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

from evaluation.adapters import OperationResult
from evaluation.ui_driver import UIDriver, UIObservation


@contextlib.contextmanager
def _open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open SQLite, commit on success, and ALWAYS close handle (required on Windows)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)


def _html_visible_text(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw_html)
    return "\n".join(parser.parts)


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> OperationResult:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return OperationResult(ok=True, status_code=resp.status, data=json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return OperationResult(ok=False, status_code=exc.code, error=raw)


def _http_html(method: str, url: str, form: dict[str, str] | None = None) -> tuple[int, str]:
    body = None
    headers: dict[str, str] = {}
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


@dataclass
class FaultFlags:
    build_fail: bool = False
    allow_empty_title: bool = False
    allow_invalid_status: bool = False
    lose_data_on_restart: bool = False
    case_sensitive_tags: bool = False
    keep_orphan_links: bool = False
    allow_overdraft: bool = False
    allow_bad_quantity: bool = False


class _ReferenceServer:
    def __init__(self, db_path: Path, handler_factory) -> None:
        self.db_path = db_path
        self._handler_factory = handler_factory
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def start(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_factory(self.db_path))
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


class HTMLFormUIDriver:
    """Real HTTP HTML form driver used to exercise reference HTML pages in tests."""

    def __init__(self, base_url_getter) -> None:
        self._base_url_getter = base_url_getter

    def run_a1_create_and_filter(
        self,
        *,
        title: str,
        status: str,
        due: str,
        filter_status: str,
    ) -> UIObservation:
        base = self._base_url_getter()
        _http_html("POST", f"{base}/ui/tasks", {"title": title, "status": status, "due": due})
        url = f"{base}/ui?status={urllib.parse.quote(filter_status)}"
        _, body = _http_html("GET", url)
        return UIObservation(visible_text=_html_visible_text(body), url=url)

    def run_a2_search_and_open(self, *, query: str) -> UIObservation:
        base = self._base_url_getter()
        url = f"{base}/ui?q={urllib.parse.quote(query)}"
        _, body = _http_html("GET", url)
        return UIObservation(visible_text=_html_visible_text(body), url=url)

    def run_a3_stock_in_and_view_history(
        self,
        *,
        item_name: str,
        quantity: int,
    ) -> UIObservation:
        base = self._base_url_getter()
        _http_html(
            "POST",
            f"{base}/ui/movements",
            {"item_name": item_name, "type": "nhập", "quantity": str(quantity)},
        )
        url = f"{base}/ui/history?item_name={urllib.parse.quote(item_name)}"
        _, body = _http_html("GET", url)
        return UIObservation(visible_text=_html_visible_text(body), url=url)


# ---------------------------------------------------------------------------
# A1 Reference App
# ---------------------------------------------------------------------------


def _a1_init_db(db_path: Path) -> None:
    with _open_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                due TEXT NOT NULL
            )
            """
        )


def _make_a1_handler(faults: FaultFlags):
    def factory(db_path: Path):
        _a1_init_db(db_path)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def _send_json(self, code: int, data: Any) -> None:
                raw = json.dumps(data).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_html(self, code: int, markup: str) -> None:
                raw = markup.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(length) if length > 0 else b""

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                status_filter = qs.get("status", [None])[0]
                with _open_db(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    if status_filter:
                        rows = conn.execute(
                            "SELECT id, title, status, due FROM tasks WHERE status = ? ORDER BY id",
                            (status_filter,),
                        ).fetchall()
                    else:
                        rows = conn.execute("SELECT id, title, status, due FROM tasks ORDER BY id").fetchall()
                items = [dict(r) for r in rows]
                if parsed.path == "/ui":
                    li = "".join(
                        f"<li>{html.escape(r['title'])} | {html.escape(r['status'])} | {html.escape(r['due'])}</li>"
                        for r in items
                    )
                    self._send_html(200, f"<html><body><ul>{li}</ul></body></html>")
                    return
                if parsed.path == "/api/tasks":
                    self._send_json(200, items)
                    return
                self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/ui/tasks":
                    form = urllib.parse.parse_qs(self._read_body().decode("utf-8"))
                    title = form.get("title", [""])[0]
                    status = form.get("status", ["todo"])[0]
                    due = form.get("due", [""])[0]
                    with _open_db(db_path) as conn:
                        conn.execute("INSERT INTO tasks(title, status, due) VALUES(?,?,?)", (title, status, due))
                    self._send_html(200, "<html><body>ok</body></html>")
                    return
                if parsed.path == "/api/tasks":
                    payload = json.loads(self._read_body().decode("utf-8"))
                    title = str(payload.get("title", ""))
                    status = str(payload.get("status", "todo"))
                    due = str(payload.get("due", ""))
                    if not faults.allow_empty_title and not title.strip():
                        self._send_json(422, {"error": "empty_title"})
                        return
                    if not faults.allow_invalid_status and status not in {"todo", "doing", "done"}:
                        self._send_json(422, {"error": "invalid_status"})
                        return
                    with _open_db(db_path) as conn:
                        cur = conn.execute(
                            "INSERT INTO tasks(title, status, due) VALUES(?,?,?)",
                            (title, status, due),
                        )
                        tid = cur.lastrowid
                    self._send_json(201, {"id": str(tid), "title": title, "status": status, "due": due})
                    return
                self._send_json(404, {"error": "not_found"})

            def do_PATCH(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if not parsed.path.startswith("/api/tasks/"):
                    self._send_json(404, {"error": "not_found"})
                    return
                tid = parsed.path.rsplit("/", 1)[-1]
                payload = json.loads(self._read_body().decode("utf-8"))
                with _open_db(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT id, title, status, due FROM tasks WHERE id = ?", (tid,)).fetchone()
                    if row is None:
                        self._send_json(404, {"error": "not_found"})
                        return
                    title = str(payload.get("title", row["title"]))
                    status = str(payload.get("status", row["status"]))
                    due = str(payload.get("due", row["due"]))
                    if not faults.allow_empty_title and not title.strip():
                        self._send_json(422, {"error": "empty_title"})
                        return
                    if not faults.allow_invalid_status and status not in {"todo", "doing", "done"}:
                        self._send_json(422, {"error": "invalid_status"})
                        return
                    conn.execute(
                        "UPDATE tasks SET title = ?, status = ?, due = ? WHERE id = ?",
                        (title, status, due, tid),
                    )
                self._send_json(200, {"id": str(tid), "title": title, "status": status, "due": due})

            def do_DELETE(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if not parsed.path.startswith("/api/tasks/"):
                    self._send_json(404, {"error": "not_found"})
                    return
                tid = parsed.path.rsplit("/", 1)[-1]
                with _open_db(db_path) as conn:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
                self._send_json(200, {"deleted": tid})

        return Handler

    return factory


class ReferenceA1Adapter:
    case_id = "A1"

    def __init__(self, tmp_dir: Path, faults: FaultFlags | None = None, ui_driver: UIDriver | None = None) -> None:
        self.tmp_dir = tmp_dir
        self.db_path = tmp_dir / "a1.sqlite"
        self.faults = faults or FaultFlags()
        self._srv = _ReferenceServer(self.db_path, _make_a1_handler(self.faults))
        self.ui_driver: UIDriver | None = (
            ui_driver if ui_driver is not None else HTMLFormUIDriver(lambda: self._srv.base_url)
        )
        self._srv.start()

    def close(self) -> None:
        self._srv.stop()

    def build_check(self) -> tuple[bool, str]:
        if self.faults.build_fail:
            return False, "simulated frontend/backend build failure"
        return True, "reference A1 build ok"

    def reset_clean_db(self) -> None:
        self._srv.stop()
        self.db_path.unlink(missing_ok=True)
        self._srv.start()

    def restart(self) -> None:
        self._srv.stop()
        if self.faults.lose_data_on_restart:
            self.db_path.unlink(missing_ok=True)
        self._srv.start()

    def create_task(self, *, title: str, status: str, due: str) -> OperationResult:
        return _http_json("POST", f"{self._srv.base_url}/api/tasks", {"title": title, "status": status, "due": due})

    def list_tasks(self, *, status: str | None = None) -> OperationResult:
        url = f"{self._srv.base_url}/api/tasks"
        if status is not None:
            url += f"?status={urllib.parse.quote(status)}"
        return _http_json("GET", url)

    def update_task(self, task_id: str, **fields: Any) -> OperationResult:
        return _http_json("PATCH", f"{self._srv.base_url}/api/tasks/{task_id}", fields)

    def delete_task(self, task_id: str) -> OperationResult:
        return _http_json("DELETE", f"{self._srv.base_url}/api/tasks/{task_id}")


# ---------------------------------------------------------------------------
# A2 Reference App
# ---------------------------------------------------------------------------


def _a2_init_db(db_path: Path) -> None:
    with _open_db(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, lower_name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS note_tags (
                note_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (note_id, tag_id)
            )
            """
        )


def _make_a2_handler(faults: FaultFlags):
    def factory(db_path: Path):
        _a2_init_db(db_path)

        def fetch_notes(conn: sqlite3.Connection, query: str | None = None, tag: str | None = None) -> list[dict[str, Any]]:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, title, body FROM notes ORDER BY id").fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                trows = conn.execute(
                    """
                    SELECT t.id, t.name FROM note_tags nt
                    LEFT JOIN tags t ON t.id = nt.tag_id
                    WHERE nt.note_id = ?
                    ORDER BY nt.tag_id
                    """,
                    (row["id"],),
                ).fetchall()
                tag_list = [
                    {"id": str(tr["id"]), "name": tr["name"] if tr["name"] is not None else "orphan"}
                    for tr in trows
                ]
                note = {"id": str(row["id"]), "title": row["title"], "body": row["body"], "tags": tag_list}
                if query is not None:
                    q = query.lower()
                    if q not in note["title"].lower() and q not in note["body"].lower():
                        continue
                if tag is not None:
                    if tag.lower() not in {t["name"].lower() for t in tag_list}:
                        continue
                out.append(note)
            return out

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def _send_json(self, code: int, data: Any) -> None:
                raw = json.dumps(data).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_html(self, code: int, markup: str) -> None:
                raw = markup.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(length) if length > 0 else b""

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                with _open_db(db_path) as conn:
                    if parsed.path == "/ui":
                        notes = fetch_notes(conn, query=qs.get("q", [None])[0])
                        blocks = "".join(
                            f"<article><h2>{html.escape(n['title'])}</h2><p>{html.escape(n['body'])}</p></article>"
                            for n in notes
                        )
                        self._send_html(200, f"<html><body>{blocks}</body></html>")
                        return
                    if parsed.path == "/api/notes":
                        notes = fetch_notes(conn, query=qs.get("q", [None])[0], tag=qs.get("tag", [None])[0])
                        self._send_json(200, notes)
                        return
                    if parsed.path.startswith("/api/notes/"):
                        nid = parsed.path.rsplit("/", 1)[-1]
                        matches = [n for n in fetch_notes(conn) if n["id"] == nid]
                        if not matches:
                            self._send_json(404, {"error": "not_found"})
                            return
                        self._send_json(200, matches[0])
                        return
                    if parsed.path == "/api/tags":
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute("SELECT id, name FROM tags ORDER BY id").fetchall()
                        self._send_json(200, [{"id": str(r["id"]), "name": r["name"]} for r in rows])
                        return
                self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                payload = json.loads(self._read_body().decode("utf-8"))
                with _open_db(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    if parsed.path == "/api/notes":
                        cur = conn.execute(
                            "INSERT INTO notes(title, body) VALUES(?,?)",
                            (payload["title"], payload["body"]),
                        )
                        self._send_json(201, {"id": str(cur.lastrowid), "title": payload["title"], "body": payload["body"], "tags": []})
                        return
                    if parsed.path == "/api/tags":
                        name = str(payload["name"])
                        low = name.lower()
                        if not faults.case_sensitive_tags:
                            existing = conn.execute("SELECT id, name FROM tags WHERE lower_name = ?", (low,)).fetchone()
                            if existing is not None:
                                self._send_json(200, {"id": str(existing["id"]), "name": existing["name"]})
                                return
                        cur = conn.execute("INSERT INTO tags(name, lower_name) VALUES(?,?)", (name, low))
                        self._send_json(201, {"id": str(cur.lastrowid), "name": name})
                        return
                    if parsed.path == "/api/note-tags":
                        conn.execute(
                            "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES(?,?)",
                            (int(payload["note_id"]), int(payload["tag_id"])),
                        )
                        self._send_json(201, {"attached": True})
                        return
                self._send_json(404, {"error": "not_found"})

            def do_PATCH(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                payload = json.loads(self._read_body().decode("utf-8"))
                with _open_db(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    if parsed.path.startswith("/api/notes/"):
                        nid = parsed.path.rsplit("/", 1)[-1]
                        row = conn.execute("SELECT id, title, body FROM notes WHERE id = ?", (nid,)).fetchone()
                        if row is None:
                            self._send_json(404, {"error": "not_found"})
                            return
                        title = payload.get("title", row["title"])
                        body = payload.get("body", row["body"])
                        conn.execute("UPDATE notes SET title = ?, body = ? WHERE id = ?", (title, body, nid))
                        self._send_json(200, {"id": nid, "title": title, "body": body})
                        return
                    if parsed.path.startswith("/api/tags/"):
                        tid = parsed.path.rsplit("/", 1)[-1]
                        name = str(payload["name"])
                        conn.execute("UPDATE tags SET name = ?, lower_name = ? WHERE id = ?", (name, name.lower(), tid))
                        self._send_json(200, {"id": tid, "name": name})
                        return
                self._send_json(404, {"error": "not_found"})

            def do_DELETE(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                with _open_db(db_path) as conn:
                    if parsed.path.startswith("/api/notes/"):
                        nid = parsed.path.rsplit("/", 1)[-1]
                        conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
                        if not faults.keep_orphan_links:
                            conn.execute("DELETE FROM note_tags WHERE note_id = ?", (nid,))
                        self._send_json(200, {"deleted": nid})
                        return
                    if parsed.path.startswith("/api/tags/"):
                        tid = parsed.path.rsplit("/", 1)[-1]
                        conn.execute("DELETE FROM tags WHERE id = ?", (tid,))
                        if not faults.keep_orphan_links:
                            conn.execute("DELETE FROM note_tags WHERE tag_id = ?", (tid,))
                        self._send_json(200, {"deleted": tid})
                        return
                self._send_json(404, {"error": "not_found"})

        return Handler

    return factory


class ReferenceA2Adapter:
    case_id = "A2"

    def __init__(self, tmp_dir: Path, faults: FaultFlags | None = None, ui_driver: UIDriver | None = None) -> None:
        self.tmp_dir = tmp_dir
        self.db_path = tmp_dir / "a2.sqlite"
        self.faults = faults or FaultFlags()
        self._srv = _ReferenceServer(self.db_path, _make_a2_handler(self.faults))
        self.ui_driver: UIDriver | None = (
            ui_driver if ui_driver is not None else HTMLFormUIDriver(lambda: self._srv.base_url)
        )
        self._srv.start()

    def close(self) -> None:
        self._srv.stop()

    def build_check(self) -> tuple[bool, str]:
        if self.faults.build_fail:
            return False, "simulated build failure"
        return True, "reference A2 build ok"

    def reset_clean_db(self) -> None:
        self._srv.stop()
        self.db_path.unlink(missing_ok=True)
        self._srv.start()

    def restart(self) -> None:
        self._srv.stop()
        if self.faults.lose_data_on_restart:
            self.db_path.unlink(missing_ok=True)
        self._srv.start()

    def create_note(self, *, title: str, body: str) -> OperationResult:
        return _http_json("POST", f"{self._srv.base_url}/api/notes", {"title": title, "body": body})

    def list_notes(self, *, query: str | None = None, tag: str | None = None) -> OperationResult:
        params = {}
        if query is not None:
            params["q"] = query
        if tag is not None:
            params["tag"] = tag
        suffix = f"?{urllib.parse.urlencode(params)}" if params else ""
        return _http_json("GET", f"{self._srv.base_url}/api/notes{suffix}")

    def get_note(self, note_id: str) -> OperationResult:
        return _http_json("GET", f"{self._srv.base_url}/api/notes/{note_id}")

    def update_note(self, note_id: str, **fields: Any) -> OperationResult:
        return _http_json("PATCH", f"{self._srv.base_url}/api/notes/{note_id}", fields)

    def delete_note(self, note_id: str) -> OperationResult:
        return _http_json("DELETE", f"{self._srv.base_url}/api/notes/{note_id}")

    def create_tag(self, *, name: str) -> OperationResult:
        return _http_json("POST", f"{self._srv.base_url}/api/tags", {"name": name})

    def list_tags(self) -> OperationResult:
        return _http_json("GET", f"{self._srv.base_url}/api/tags")

    def rename_tag(self, tag_id: str, *, name: str) -> OperationResult:
        return _http_json("PATCH", f"{self._srv.base_url}/api/tags/{tag_id}", {"name": name})

    def delete_tag(self, tag_id: str) -> OperationResult:
        return _http_json("DELETE", f"{self._srv.base_url}/api/tags/{tag_id}")

    def attach_tag(self, note_id: str, tag_id: str) -> OperationResult:
        return _http_json("POST", f"{self._srv.base_url}/api/note-tags", {"note_id": note_id, "tag_id": tag_id})


# ---------------------------------------------------------------------------
# A3 Reference App
# ---------------------------------------------------------------------------


def _a3_init_db(db_path: Path) -> None:
    with _open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, balance INTEGER NOT NULL)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                quantity INTEGER NOT NULL
            )
            """
        )


def _make_a3_handler(faults: FaultFlags):
    def factory(db_path: Path):
        _a3_init_db(db_path)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def _send_json(self, code: int, data: Any) -> None:
                raw = json.dumps(data).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_html(self, code: int, markup: str) -> None:
                raw = markup.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(length) if length > 0 else b""

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                with _open_db(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    if parsed.path == "/ui/history":
                        name = qs.get("item_name", [""])[0]
                        item = conn.execute("SELECT id, name, balance FROM items WHERE name = ?", (name,)).fetchone()
                        if item is None:
                            self._send_html(404, "<html><body>not found</body></html>")
                            return
                        mvs = conn.execute(
                            "SELECT type, quantity FROM movements WHERE item_id = ? ORDER BY id",
                            (item["id"],),
                        ).fetchall()
                        rows_html = "".join(f"<li>{html.escape(m['type'])} {m['quantity']}</li>" for m in mvs)
                        self._send_html(
                            200,
                            f"<html><body><h1>{html.escape(item['name'])}</h1><p>Tồn: {item['balance']}</p><ul>{rows_html}</ul></body></html>",
                        )
                        return
                    if parsed.path == "/api/items":
                        rows = conn.execute("SELECT id, name, balance FROM items ORDER BY id").fetchall()
                        self._send_json(200, [{"id": str(r["id"]), "name": r["name"], "balance": r["balance"]} for r in rows])
                        return
                    if parsed.path == "/api/movements":
                        item_id = qs.get("item_id", [None])[0]
                        if item_id is not None:
                            rows = conn.execute(
                                "SELECT id, item_id, type, quantity FROM movements WHERE item_id = ? ORDER BY id",
                                (item_id,),
                            ).fetchall()
                        else:
                            rows = conn.execute("SELECT id, item_id, type, quantity FROM movements ORDER BY id").fetchall()
                        self._send_json(
                            200,
                            [
                                {"id": str(r["id"]), "item_id": str(r["item_id"]), "type": r["type"], "quantity": r["quantity"]}
                                for r in rows
                            ],
                        )
                        return
                self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/ui/movements":
                    form = urllib.parse.parse_qs(self._read_body().decode("utf-8"))
                    name = form.get("item_name", [""])[0]
                    mv_type = form.get("type", ["nhập"])[0]
                    qty = int(form.get("quantity", ["0"])[0])
                    with _open_db(db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        item = conn.execute("SELECT id, balance FROM items WHERE name = ?", (name,)).fetchone()
                        if item is not None:
                            delta = qty if mv_type == "nhập" else -qty
                            conn.execute("UPDATE items SET balance = ? WHERE id = ?", (item["balance"] + delta, item["id"]))
                            conn.execute(
                                "INSERT INTO movements(item_id, type, quantity) VALUES(?,?,?)",
                                (item["id"], mv_type, qty),
                            )
                    self._send_html(200, "<html><body>ok</body></html>")
                    return
                payload = json.loads(self._read_body().decode("utf-8"))
                with _open_db(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    if parsed.path == "/api/items":
                        cur = conn.execute(
                            "INSERT INTO items(name, balance) VALUES(?,?)",
                            (payload["name"], int(payload.get("opening_balance", 0))),
                        )
                        self._send_json(
                            201,
                            {"id": str(cur.lastrowid), "name": payload["name"], "balance": int(payload.get("opening_balance", 0))},
                        )
                        return
                    if parsed.path == "/api/movements":
                        item_id = int(payload["item_id"])
                        mv_type = str(payload["type"])
                        qty = payload["quantity"]
                        if not faults.allow_bad_quantity:
                            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                                self._send_json(422, {"error": "quantity_must_be_positive_int"})
                                return
                        item = conn.execute("SELECT id, balance FROM items WHERE id = ?", (item_id,)).fetchone()
                        if item is None:
                            self._send_json(404, {"error": "not_found"})
                            return
                        delta = int(qty) if mv_type == "nhập" else -int(qty)
                        next_balance = int(item["balance"]) + delta
                        if not faults.allow_overdraft and next_balance < 0:
                            self._send_json(422, {"error": "insufficient_stock"})
                            return
                        conn.execute("UPDATE items SET balance = ? WHERE id = ?", (next_balance, item_id))
                        cur = conn.execute(
                            "INSERT INTO movements(item_id, type, quantity) VALUES(?,?,?)",
                            (item_id, mv_type, int(qty)),
                        )
                        self._send_json(
                            201,
                            {"id": str(cur.lastrowid), "item_id": str(item_id), "type": mv_type, "quantity": int(qty)},
                        )
                        return
                self._send_json(404, {"error": "not_found"})

        return Handler

    return factory


class ReferenceA3Adapter:
    case_id = "A3"

    def __init__(self, tmp_dir: Path, faults: FaultFlags | None = None, ui_driver: UIDriver | None = None) -> None:
        self.tmp_dir = tmp_dir
        self.db_path = tmp_dir / "a3.sqlite"
        self.faults = faults or FaultFlags()
        self._srv = _ReferenceServer(self.db_path, _make_a3_handler(self.faults))
        self.ui_driver: UIDriver | None = (
            ui_driver if ui_driver is not None else HTMLFormUIDriver(lambda: self._srv.base_url)
        )
        self._srv.start()

    def close(self) -> None:
        self._srv.stop()

    def build_check(self) -> tuple[bool, str]:
        if self.faults.build_fail:
            return False, "simulated build failure"
        return True, "reference A3 build ok"

    def reset_clean_db(self) -> None:
        self._srv.stop()
        self.db_path.unlink(missing_ok=True)
        self._srv.start()

    def restart(self) -> None:
        self._srv.stop()
        if self.faults.lose_data_on_restart:
            self.db_path.unlink(missing_ok=True)
        self._srv.start()

    def create_item(self, *, name: str, opening_balance: int = 0) -> OperationResult:
        return _http_json(
            "POST",
            f"{self._srv.base_url}/api/items",
            {"name": name, "opening_balance": opening_balance},
        )

    def list_items(self) -> OperationResult:
        return _http_json("GET", f"{self._srv.base_url}/api/items")

    def record_movement(self, *, item_id: str, movement_type: str, quantity: Any) -> OperationResult:
        return _http_json(
            "POST",
            f"{self._srv.base_url}/api/movements",
            {"item_id": item_id, "type": movement_type, "quantity": quantity},
        )

    def list_movements(self, *, item_id: str | None = None) -> OperationResult:
        url = f"{self._srv.base_url}/api/movements"
        if item_id is not None:
            url += f"?item_id={urllib.parse.quote(item_id)}"
        return _http_json("GET", url)
