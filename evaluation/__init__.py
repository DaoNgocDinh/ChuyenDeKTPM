"""Independent acceptance evaluation suite for A1, A2, and A3 (E01).

Kept strictly outside Dev/Tester writable workspace roots.
"""

from evaluation.adapters import (
    AppAdapter,
    InventoryAppAdapter,
    NotesAppAdapter,
    TaskAppAdapter,
)
from evaluation.ui_driver import (
    PlaywrightUIDriver,
    StrictMissingUIDriver,
    UIDriver,
    UIDriverUnavailableError,
    UIObservation,
)

__all__ = [
    "AppAdapter",
    "InventoryAppAdapter",
    "NotesAppAdapter",
    "PlaywrightUIDriver",
    "StrictMissingUIDriver",
    "TaskAppAdapter",
    "UIDriver",
    "UIDriverUnavailableError",
    "UIObservation",
]
