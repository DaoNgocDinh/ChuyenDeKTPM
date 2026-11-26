"""Adapter interfaces separating locked E01 tests from app-specific URL/field names.

Because S and M receive only the business brief (D02-D04) without forced endpoint
names, E01 keeps all 30 criteria and expected assertions immutable while each
evaluated application provides a thin adapter mapping its own HTTP routes and UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from evaluation.ui_driver import UIDriver


@dataclass(frozen=True)
class OperationResult:
    """Normalized outcome of an HTTP/data operation against an evaluated app."""

    ok: bool
    status_code: int
    data: Any = None
    error: str = ""


@runtime_checkable
class AppAdapter(Protocol):
    """Common lifecycle hooks required for clean-DB isolation, restart, and build gate."""

    case_id: str
    ui_driver: UIDriver | None

    def build_check(self) -> tuple[bool, str]:
        """Verify the target app builds and boots cleanly before acceptance checks."""
        ...

    def reset_clean_db(self) -> None:
        """Reset storage to an empty state before each independent criterion."""
        ...

    def restart(self) -> None:
        """Restart the application process against the same persistent storage."""
        ...


@runtime_checkable
class TaskAppAdapter(AppAdapter, Protocol):
    """Adapter contract for A1 (Task Manager)."""

    def create_task(self, *, title: str, status: str, due: str) -> OperationResult: ...

    def list_tasks(self, *, status: str | None = None) -> OperationResult: ...

    def update_task(self, task_id: str, **fields: Any) -> OperationResult: ...

    def delete_task(self, task_id: str) -> OperationResult: ...


@runtime_checkable
class NotesAppAdapter(AppAdapter, Protocol):
    """Adapter contract for A2 (Tagged Notes)."""

    def create_note(self, *, title: str, body: str) -> OperationResult: ...

    def list_notes(
        self,
        *,
        query: str | None = None,
        tag: str | None = None,
    ) -> OperationResult: ...

    def get_note(self, note_id: str) -> OperationResult: ...

    def update_note(self, note_id: str, **fields: Any) -> OperationResult: ...

    def delete_note(self, note_id: str) -> OperationResult: ...

    def create_tag(self, *, name: str) -> OperationResult: ...

    def list_tags(self) -> OperationResult: ...

    def rename_tag(self, tag_id: str, *, name: str) -> OperationResult: ...

    def delete_tag(self, tag_id: str) -> OperationResult: ...

    def attach_tag(self, note_id: str, tag_id: str) -> OperationResult: ...


@runtime_checkable
class InventoryAppAdapter(AppAdapter, Protocol):
    """Adapter contract for A3 (Small Inventory)."""

    def create_item(self, *, name: str, opening_balance: int = 0) -> OperationResult: ...

    def list_items(self) -> OperationResult: ...

    def record_movement(
        self,
        *,
        item_id: str,
        movement_type: str,
        quantity: Any,
    ) -> OperationResult: ...

    def list_movements(self, *, item_id: str | None = None) -> OperationResult: ...
