"""Locked 30 deterministic acceptance criteria for A1, A2, and A3 (E01).

All fixture records and expected semantics are loaded directly from the
owner-approved specifications evaluation/A1.json, A2.json, and A3.json (D02-D04).
Each criterion begins on a clean database via adapter.reset_clean_db().
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from evaluation.adapters import (
    AppAdapter,
    InventoryAppAdapter,
    NotesAppAdapter,
    TaskAppAdapter,
)
from evaluation.ui_driver import StrictMissingUIDriver, UIDriver, UIDriverUnavailableError


EVAL_DIR = Path(__file__).resolve().parent


def load_case_spec(case_id: str, eval_dir: Path = EVAL_DIR) -> dict[str, Any]:
    if case_id not in {"A1", "A2", "A3"}:
        raise ValueError(f"Unsupported case_id: {case_id!r}")
    path = eval_dir / f"{case_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _require_ok(res, context: str) -> Any:
    if not res.ok:
        raise AssertionError(f"{context} failed (status={res.status_code}): {res.error}")
    return res.data


def _require_rejected(res, context: str) -> None:
    if res.ok:
        raise AssertionError(f"{context} must be rejected, but succeeded (status={res.status_code})")


def _require_ui_driver(adapter: AppAdapter) -> UIDriver:
    if adapter.ui_driver is None:
        return StrictMissingUIDriver("adapter.ui_driver is None")
    return adapter.ui_driver


# ---------------------------------------------------------------------------
# A1 — Task Manager (A1-01 .. A1-10)
# ---------------------------------------------------------------------------


def _task_signature(task: dict[str, Any]) -> tuple[str, str, str]:
    return (str(task["title"]), str(task["status"]), str(task["due"]))


def _check_a1_01(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t1 = spec["fixtures"]["T1"]
    _require_ok(adapter.create_task(**t1), "create T1")
    tasks = _require_ok(adapter.list_tasks(), "list tasks")
    if len(tasks) != 1 or _task_signature(tasks[0]) != _task_signature(t1):
        raise AssertionError(f"Expected single task {t1}, got {tasks}")


def _check_a1_02(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    fx = spec["fixtures"]
    for key in ("T1", "T2", "T3"):
        _require_ok(adapter.create_task(**fx[key]), f"create {key}")
    tasks = _require_ok(adapter.list_tasks(), "list all tasks")
    got = sorted(_task_signature(t) for t in tasks)
    expected = sorted(_task_signature(fx[k]) for k in ("T1", "T2", "T3"))
    if len(tasks) != 3 or got != expected:
        raise AssertionError(f"Expected 3 tasks {expected}, got {got}")


def _check_a1_03(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t1 = spec["fixtures"]["T1"]
    created = _require_ok(adapter.create_task(**t1), "create T1")
    task_id = str(created["id"])
    _require_ok(
        adapter.update_task(task_id, title="Viết đặc tả v2", due="2026-12-12"),
        "update T1",
    )
    tasks = _require_ok(adapter.list_tasks(), "list after update")
    if len(tasks) != 1:
        raise AssertionError(f"Update created duplicate or deleted task: {tasks}")
    updated = tasks[0]
    if str(updated["id"]) != task_id or _task_signature(updated) != ("Viết đặc tả v2", "todo", "2026-12-12"):
        raise AssertionError(f"Unexpected updated task: {updated}")


def _check_a1_04(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    fx = spec["fixtures"]
    created_t1 = _require_ok(adapter.create_task(**fx["T1"]), "create T1")
    _require_ok(adapter.create_task(**fx["T2"]), "create T2")
    _require_ok(adapter.delete_task(str(created_t1["id"])), "delete T1")
    tasks = _require_ok(adapter.list_tasks(), "list after delete")
    if len(tasks) != 1 or _task_signature(tasks[0]) != _task_signature(fx["T2"]):
        raise AssertionError(f"Expected only T2 remaining, got {tasks}")


def _check_a1_05(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t1 = spec["fixtures"]["T1"]
    _require_ok(adapter.create_task(**t1), "seed T1")
    res = adapter.create_task(title="", status="todo", due="2026-12-05")
    _require_rejected(res, "empty title task")
    tasks = _require_ok(adapter.list_tasks(), "list after rejected empty title")
    if len(tasks) != 1 or _task_signature(tasks[0]) != _task_signature(t1):
        raise AssertionError(f"Task list mutated after empty-title rejection: {tasks}")


def _check_a1_06(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t1 = spec["fixtures"]["T1"]
    created = _require_ok(adapter.create_task(**t1), "create T1")
    task_id = str(created["id"])
    for next_status in ("doing", "done", "todo"):
        _require_ok(adapter.update_task(task_id, status=next_status), f"set status={next_status}")
        tasks = _require_ok(adapter.list_tasks(), f"list after status={next_status}")
        if len(tasks) != 1 or _task_signature(tasks[0]) != (t1["title"], next_status, t1["due"]):
            raise AssertionError(f"Status transition {next_status} failed: {tasks}")


def _check_a1_07(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t1 = spec["fixtures"]["T1"]
    created = _require_ok(adapter.create_task(**t1), "create T1")
    res = adapter.update_task(str(created["id"]), status="archived")
    _require_rejected(res, "invalid status 'archived'")
    tasks = _require_ok(adapter.list_tasks(), "list after rejected status")
    if len(tasks) != 1 or tasks[0]["status"] != "todo":
        raise AssertionError(f"Task status changed despite invalid value: {tasks}")


def _check_a1_08(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    fx = spec["fixtures"]
    for key in ("T1", "T2", "T3"):
        _require_ok(adapter.create_task(**fx[key]), f"create {key}")
    for status, expected_key in (("todo", "T1"), ("doing", "T2"), ("done", "T3")):
        filtered = _require_ok(adapter.list_tasks(status=status), f"filter status={status}")
        if len(filtered) != 1 or _task_signature(filtered[0]) != _task_signature(fx[expected_key]):
            raise AssertionError(f"Filter {status} expected {fx[expected_key]}, got {filtered}")


def _check_a1_09(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t1 = spec["fixtures"]["T1"]
    created = _require_ok(adapter.create_task(**t1), "create T1")
    _require_ok(adapter.update_task(str(created["id"]), status="done"), "mark T1 done")
    adapter.restart()
    tasks = _require_ok(adapter.list_tasks(), "list after restart")
    if len(tasks) != 1 or _task_signature(tasks[0]) != (t1["title"], "done", t1["due"]):
        raise AssertionError(f"Data lost or corrupted after restart: {tasks}")


def _check_a1_10(adapter: TaskAppAdapter, spec: dict[str, Any]) -> None:
    t2 = spec["fixtures"]["T2"]
    driver = _require_ui_driver(adapter)
    obs = driver.run_a1_create_and_filter(
        title=t2["title"],
        status=t2["status"],
        due=t2["due"],
        filter_status="doing",
    )
    text = obs.visible_text
    for token in (t2["title"], "doing", t2["due"]):
        if token not in text:
            raise AssertionError(f"A1-10 UI output missing {token!r}; observed={text!r}")


# ---------------------------------------------------------------------------
# A2 — Tagged Notes (A2-01 .. A2-10)
# ---------------------------------------------------------------------------


def _seed_a2_fixtures(adapter: NotesAppAdapter, spec: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Seed N1, N2, N3 and their tags; return (note_ids_by_key, tag_ids_by_lower_name)."""
    fx = spec["fixtures"]
    tag_ids: dict[str, str] = {}
    note_ids: dict[str, str] = {}
    for note_key in ("N1", "N2", "N3"):
        item = fx[note_key]
        created_note = _require_ok(
            adapter.create_note(title=item["title"], body=item["body"]),
            f"create {note_key}",
        )
        nid = str(created_note["id"])
        note_ids[note_key] = nid
        for tag_name in item["tags"]:
            low = tag_name.lower()
            if low not in tag_ids:
                created_tag = _require_ok(adapter.create_tag(name=tag_name), f"create tag {tag_name}")
                tag_ids[low] = str(created_tag["id"])
            _require_ok(adapter.attach_tag(nid, tag_ids[low]), f"attach {tag_name} to {note_key}")
    return note_ids, tag_ids


def _note_tags_lower(note: dict[str, Any]) -> set[str]:
    tags = note.get("tags", [])
    result: set[str] = set()
    for t in tags:
        if isinstance(t, dict):
            result.add(str(t["name"]).lower())
        else:
            result.add(str(t).lower())
    return result


def _check_a2_01(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    n1 = spec["fixtures"]["N1"]
    created = _require_ok(adapter.create_note(title=n1["title"], body=n1["body"]), "create N1")
    fetched = _require_ok(adapter.get_note(str(created["id"])), "read N1")
    if fetched["title"] != n1["title"] or fetched["body"] != n1["body"]:
        raise AssertionError(f"Expected {n1['title']}/{n1['body']}, got {fetched}")


def _check_a2_02(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    note_ids, _ = _seed_a2_fixtures(adapter, spec)
    n2 = spec["fixtures"]["N2"]
    _require_ok(adapter.update_note(note_ids["N2"], title="Beta đã duyệt"), "update N2 title")
    fetched = _require_ok(adapter.get_note(note_ids["N2"]), "read updated N2")
    if fetched["title"] != "Beta đã duyệt" or fetched["body"] != n2["body"]:
        raise AssertionError(f"Updated N2 title/body mismatch: {fetched}")
    if _note_tags_lower(fetched) != {"work"}:
        raise AssertionError(f"Updated N2 lost Work tag: {fetched}")


def _check_a2_03(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    created = _require_ok(adapter.create_tag(name="Nháp"), "create tag Nháp")
    tags = _require_ok(adapter.list_tags(), "list tags after create")
    if [t["name"] for t in tags] != ["Nháp"]:
        raise AssertionError(f"Expected ['Nháp'], got {tags}")
    _require_ok(adapter.rename_tag(str(created["id"]), name="Công bố"), "rename tag")
    tags_after = _require_ok(adapter.list_tags(), "list tags after rename")
    names = [t["name"] for t in tags_after]
    if "Công bố" not in names or "Nháp" in names or len(names) != 1:
        raise AssertionError(f"Expected single renamed tag 'Công bố', got {tags_after}")


def _check_a2_04(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    _require_ok(adapter.create_tag(name="Work"), "create Work")
    # Clarification in D03: app may return existing tag OR reject duplicate.
    adapter.create_tag(name="work")
    tags = _require_ok(adapter.list_tags(), "list tags after case-variant duplicate")
    work_tags = [t for t in tags if str(t["name"]).lower() == "work"]
    if len(work_tags) != 1 or len(tags) != 1:
        raise AssertionError(f"Duplicate case-insensitive tag created: {tags}")


def _check_a2_05(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    note_ids, _ = _seed_a2_fixtures(adapter, spec)
    n1 = _require_ok(adapter.get_note(note_ids["N1"]), "read N1")
    n2 = _require_ok(adapter.get_note(note_ids["N2"]), "read N2")
    n3 = _require_ok(adapter.get_note(note_ids["N3"]), "read N3")
    if _note_tags_lower(n1) != {"work", "urgent"}:
        raise AssertionError(f"N1 tag mismatch: {n1}")
    if _note_tags_lower(n2) != {"work"}:
        raise AssertionError(f"N2 tag mismatch: {n2}")
    if _note_tags_lower(n3) != {"home"}:
        raise AssertionError(f"N3 tag mismatch: {n3}")
    tags = _require_ok(adapter.list_tags(), "list shared tags")
    if {str(t["name"]).lower() for t in tags} != {"work", "urgent", "home"} or len(tags) != 3:
        raise AssertionError(f"Shared tag Work was duplicated or missing: {tags}")


def _check_a2_06(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    _seed_a2_fixtures(adapter, spec)
    found = _require_ok(adapter.list_notes(query="lPh"), "search 'lPh'")
    titles = [n["title"] for n in found]
    if titles != [spec["fixtures"]["N1"]["title"]]:
        raise AssertionError(f"Substring search 'lPh' expected only N1, got {titles}")


def _check_a2_07(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    _seed_a2_fixtures(adapter, spec)
    fx = spec["fixtures"]
    work_notes = _require_ok(adapter.list_notes(tag="Work"), "filter Work")
    home_notes = _require_ok(adapter.list_notes(tag="Home"), "filter Home")
    if {n["title"] for n in work_notes} != {fx["N1"]["title"], fx["N2"]["title"]} or len(work_notes) != 2:
        raise AssertionError(f"Work filter mismatch: {work_notes}")
    if [n["title"] for n in home_notes] != [fx["N3"]["title"]]:
        raise AssertionError(f"Home filter mismatch: {home_notes}")


def _check_a2_08(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    note_ids, _ = _seed_a2_fixtures(adapter, spec)
    fx = spec["fixtures"]
    _require_ok(adapter.delete_note(note_ids["N1"]), "delete N1")
    all_notes = _require_ok(adapter.list_notes(), "list all notes after deleting N1")
    if {n["title"] for n in all_notes} != {fx["N2"]["title"], fx["N3"]["title"]}:
        raise AssertionError(f"Notes after deleting N1 mismatch: {all_notes}")
    work_notes = _require_ok(adapter.list_notes(tag="Work"), "filter Work after deleting N1")
    if [n["title"] for n in work_notes] != [fx["N2"]["title"]]:
        raise AssertionError(f"Orphan link or lost N2 on Work tag: {work_notes}")


def _check_a2_09(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    note_ids, tag_ids = _seed_a2_fixtures(adapter, spec)
    _require_ok(adapter.delete_tag(tag_ids["work"]), "delete Work tag")
    tags = _require_ok(adapter.list_tags(), "list tags after deleting Work")
    if "work" in {str(t["name"]).lower() for t in tags}:
        raise AssertionError(f"Work tag still present: {tags}")
    n1 = _require_ok(adapter.get_note(note_ids["N1"]), "read N1 after deleting Work")
    n2 = _require_ok(adapter.get_note(note_ids["N2"]), "read N2 after deleting Work")
    n3 = _require_ok(adapter.get_note(note_ids["N3"]), "read N3 after deleting Work")
    if _note_tags_lower(n1) != {"urgent"}:
        raise AssertionError(f"N1 tags expected {{'urgent'}}, got {n1}")
    if _note_tags_lower(n2) != set():
        raise AssertionError(f"N2 still has orphan tag: {n2}")
    if _note_tags_lower(n3) != {"home"}:
        raise AssertionError(f"N3 tags expected {{'home'}}, got {n3}")


def _check_a2_10(adapter: NotesAppAdapter, spec: dict[str, Any]) -> None:
    _seed_a2_fixtures(adapter, spec)
    fx = spec["fixtures"]
    driver = _require_ui_driver(adapter)
    obs = driver.run_a2_search_and_open(query="eTa")
    text = obs.visible_text
    if fx["N2"]["title"] not in text or fx["N2"]["body"] not in text:
        raise AssertionError(f"A2-10 UI output missing N2 content; observed={text!r}")
    if fx["N1"]["title"] in text or fx["N3"]["title"] in text:
        raise AssertionError(f"A2-10 UI output leaked non-matching notes; observed={text!r}")


# ---------------------------------------------------------------------------
# A3 — Small Inventory (A3-01 .. A3-10)
# ---------------------------------------------------------------------------


def _seed_a3_items(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> dict[str, str]:
    fx = spec["fixtures"]
    ids: dict[str, str] = {}
    for key in ("K1", "K2"):
        item = fx[key]
        created = _require_ok(
            adapter.create_item(name=item["name"], opening_balance=item["opening_balance"]),
            f"create {key}",
        )
        ids[key] = str(created["id"])
    return ids


def _seed_a3_full(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> dict[str, str]:
    ids = _seed_a3_items(adapter, spec)
    for mv in spec["fixtures"]["movements"]:
        _require_ok(
            adapter.record_movement(
                item_id=ids[mv["item"]],
                movement_type=mv["type"],
                quantity=mv["quantity"],
            ),
            f"seed movement {mv}",
        )
    return ids


def _find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if str(item["id"]) == item_id:
            return item
    raise AssertionError(f"Item {item_id} not found in {items}")


def _normalize_mv_type(raw: str) -> str:
    val = str(raw).strip().lower()
    if val in {"nhập", "nhap", "in", "import", "stock_in"}:
        return "nhập"
    if val in {"xuất", "xuat", "out", "export", "stock_out"}:
        return "xuất"
    return val


def _check_a3_01(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_items(adapter, spec)
    items = _require_ok(adapter.list_items(), "list items")
    if len(items) != 2 or ids["K1"] == ids["K2"]:
        raise AssertionError(f"Expected 2 distinct items, got {items}")
    k1 = _find_item(items, ids["K1"])
    k2 = _find_item(items, ids["K2"])
    if k1["name"] != "Bút xanh" or int(k1["balance"]) != 0:
        raise AssertionError(f"Unexpected K1: {k1}")
    if k2["name"] != "Sổ tay" or int(k2["balance"]) != 0:
        raise AssertionError(f"Unexpected K2: {k2}")


def _check_a3_02(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_items(adapter, spec)
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="nhập", quantity=5), "in 5")
    k1 = _find_item(_require_ok(adapter.list_items(), "list items"), ids["K1"])
    if int(k1["balance"]) != 5:
        raise AssertionError(f"Expected K1 balance=5, got {k1}")


def _check_a3_03(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_items(adapter, spec)
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="nhập", quantity=5), "in 5")
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="xuất", quantity=2), "out 2")
    k1 = _find_item(_require_ok(adapter.list_items(), "list items"), ids["K1"])
    if int(k1["balance"]) != 3:
        raise AssertionError(f"Expected K1 balance=3, got {k1}")


def _check_a3_04(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_items(adapter, spec)
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="nhập", quantity=5), "in 5")
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="xuất", quantity=5), "out 5")
    k1 = _find_item(_require_ok(adapter.list_items(), "list items"), ids["K1"])
    if int(k1["balance"]) != 0:
        raise AssertionError(f"Expected K1 balance=0, got {k1}")


def _check_a3_05(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_items(adapter, spec)
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="nhập", quantity=5), "seed in 5")
    for mv_type in ("nhập", "xuất"):
        for bad_qty in (0, -1, 1.5):
            res = adapter.record_movement(item_id=ids["K1"], movement_type=mv_type, quantity=bad_qty)
            _require_rejected(res, f"invalid quantity {bad_qty} for {mv_type}")
    k1 = _find_item(_require_ok(adapter.list_items(), "list items"), ids["K1"])
    history = _require_ok(adapter.list_movements(item_id=ids["K1"]), "K1 history")
    if int(k1["balance"]) != 5 or len(history) != 1:
        raise AssertionError(f"Invalid movement mutated state: item={k1}, history={history}")


def _check_a3_06(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_items(adapter, spec)
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="nhập", quantity=3), "seed in 3")
    res = adapter.record_movement(item_id=ids["K1"], movement_type="xuất", quantity=4)
    _require_rejected(res, "overdraft stock out 4 > 3")
    k1 = _find_item(_require_ok(adapter.list_items(), "list items"), ids["K1"])
    history = _require_ok(adapter.list_movements(item_id=ids["K1"]), "K1 history")
    if int(k1["balance"]) != 3 or len(history) != 1:
        raise AssertionError(f"Overdraft mutated state: item={k1}, history={history}")


def _check_a3_07(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_full(adapter, spec)
    h1 = _require_ok(adapter.list_movements(item_id=ids["K1"]), "K1 history")
    h2 = _require_ok(adapter.list_movements(item_id=ids["K2"]), "K2 history")
    sig1 = [(_normalize_mv_type(m["type"]), int(m["quantity"])) for m in h1]
    sig2 = [(_normalize_mv_type(m["type"]), int(m["quantity"])) for m in h2]
    if sig1 != [("nhập", 5), ("xuất", 2)]:
        raise AssertionError(f"K1 history mismatch: {sig1}")
    if sig2 != [("nhập", 4)]:
        raise AssertionError(f"K2 history mismatch: {sig2}")


def _check_a3_08(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_full(adapter, spec)
    _require_ok(adapter.record_movement(item_id=ids["K1"], movement_type="nhập", quantity=1), "K1 in +1")
    items = _require_ok(adapter.list_items(), "list items")
    for key, expected_balance, expected_count in (("K1", 4, 3), ("K2", 4, 1)):
        item = _find_item(items, ids[key])
        history = _require_ok(adapter.list_movements(item_id=ids[key]), f"{key} history")
        reconciled = sum(
            int(m["quantity"]) if _normalize_mv_type(m["type"]) == "nhập" else -int(m["quantity"])
            for m in history
        )
        if int(item["balance"]) != expected_balance or reconciled != expected_balance or len(history) != expected_count:
            raise AssertionError(
                f"{key} reconciliation failed: balance={item['balance']}, reconciled={reconciled}, count={len(history)}"
            )


def _check_a3_09(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    ids = _seed_a3_full(adapter, spec)
    adapter.restart()
    items = _require_ok(adapter.list_items(), "list items after restart")
    k1 = _find_item(items, ids["K1"])
    k2 = _find_item(items, ids["K2"])
    h1 = _require_ok(adapter.list_movements(item_id=ids["K1"]), "K1 history after restart")
    h2 = _require_ok(adapter.list_movements(item_id=ids["K2"]), "K2 history after restart")
    if int(k1["balance"]) != 3 or int(k2["balance"]) != 4:
        raise AssertionError(f"Balances corrupted after restart: K1={k1}, K2={k2}")
    if len(h1) != 2 or len(h2) != 1:
        raise AssertionError(f"Movements lost after restart: h1={h1}, h2={h2}")


def _check_a3_10(adapter: InventoryAppAdapter, spec: dict[str, Any]) -> None:
    _seed_a3_items(adapter, spec)
    driver = _require_ui_driver(adapter)
    obs = driver.run_a3_stock_in_and_view_history(item_name="Bút xanh", quantity=5)
    text = obs.visible_text
    for token in ("Bút xanh", "5", "nhập"):
        if token.lower() not in text.lower():
            raise AssertionError(f"A3-10 UI output missing {token!r}; observed={text!r}")


CRITERIA_CHECKS: dict[str, dict[str, Callable[[Any, dict[str, Any]], None]]] = {
    "A1": {
        "A1-01": _check_a1_01,
        "A1-02": _check_a1_02,
        "A1-03": _check_a1_03,
        "A1-04": _check_a1_04,
        "A1-05": _check_a1_05,
        "A1-06": _check_a1_06,
        "A1-07": _check_a1_07,
        "A1-08": _check_a1_08,
        "A1-09": _check_a1_09,
        "A1-10": _check_a1_10,
    },
    "A2": {
        "A2-01": _check_a2_01,
        "A2-02": _check_a2_02,
        "A2-03": _check_a2_03,
        "A2-04": _check_a2_04,
        "A2-05": _check_a2_05,
        "A2-06": _check_a2_06,
        "A2-07": _check_a2_07,
        "A2-08": _check_a2_08,
        "A2-09": _check_a2_09,
        "A2-10": _check_a2_10,
    },
    "A3": {
        "A3-01": _check_a3_01,
        "A3-02": _check_a3_02,
        "A3-03": _check_a3_03,
        "A3-04": _check_a3_04,
        "A3-05": _check_a3_05,
        "A3-06": _check_a3_06,
        "A3-07": _check_a3_07,
        "A3-08": _check_a3_08,
        "A3-09": _check_a3_09,
        "A3-10": _check_a3_10,
    },
}


def run_criteria_for_case(case_id: str, adapter: AppAdapter) -> list[dict[str, Any]]:
    spec = load_case_spec(case_id)
    checks = CRITERIA_CHECKS[case_id]
    results: list[dict[str, Any]] = []
    for entry in spec["criteria"]:
        cid = entry["id"]
        title = entry["title"]
        fn = checks[cid]
        started = time.monotonic()
        try:
            adapter.reset_clean_db()
            fn(adapter, spec)
            status = "passed"
            message = ""
        except AssertionError as exc:
            status = "failed"
            message = str(exc)
        except UIDriverUnavailableError as exc:
            status = "error"
            message = str(exc)
        except Exception as exc:  # noqa: BLE001
            status = "error"
            message = f"{type(exc).__name__}: {exc}"
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        results.append(
            {
                "criterion_id": cid,
                "title": title,
                "status": status,
                "duration_ms": duration_ms,
                "message": message,
            }
        )
    return results
