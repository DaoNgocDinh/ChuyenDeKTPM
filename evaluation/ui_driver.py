"""Independent UI driver contracts for A1-10, A2-10, and A3-10.

Frontend acceptance criteria MUST execute a real UI flow and MUST NOT be inferred
from backend API tests. Playwright is imported lazily only when invoked in an
evaluation environment that has Playwright installed, keeping I01's platform
pyproject.toml/uv.lock untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class UIDriverUnavailableError(RuntimeError):
    """Raised when a UI criterion is executed without a real browser/UI driver."""


@dataclass(frozen=True)
class UIObservation:
    """Observable page text and structured matches captured from a real UI run."""

    visible_text: str
    url: str = ""
    details: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class UIDriver(Protocol):
    """Minimum browser interaction contract for the three UI criteria (A1-10, A2-10, A3-10)."""

    def run_a1_create_and_filter(
        self,
        *,
        title: str,
        status: str,
        due: str,
        filter_status: str,
    ) -> UIObservation: ...

    def run_a2_search_and_open(self, *, query: str) -> UIObservation: ...

    def run_a3_stock_in_and_view_history(
        self,
        *,
        item_name: str,
        quantity: int,
    ) -> UIObservation: ...


class StrictMissingUIDriver:
    """Default fail-closed driver that refuses to infer UI pass from backend tests."""

    def __init__(self, reason: str = "UI driver is not configured for this evaluation run") -> None:
        self.reason = reason

    def run_a1_create_and_filter(
        self,
        *,
        title: str,
        status: str,
        due: str,
        filter_status: str,
    ) -> UIObservation:
        raise UIDriverUnavailableError(f"A1-10 cannot pass without a real UI driver: {self.reason}")

    def run_a2_search_and_open(self, *, query: str) -> UIObservation:
        raise UIDriverUnavailableError(f"A2-10 cannot pass without a real UI driver: {self.reason}")

    def run_a3_stock_in_and_view_history(
        self,
        *,
        item_name: str,
        quantity: int,
    ) -> UIObservation:
        raise UIDriverUnavailableError(f"A3-10 cannot pass without a real UI driver: {self.reason}")


@dataclass(frozen=True)
class PlaywrightSelectors:
    """App-specific selectors supplied by the evaluator per generated frontend."""

    a1_title_input: str = "[name='title']"
    a1_status_select: str = "[name='status']"
    a1_due_input: str = "[name='due']"
    a1_submit_button: str = "button[type='submit']"
    a1_filter_select: str = "[name='filter_status']"
    a2_search_input: str = "[name='q']"
    a2_search_submit: str = "button[type='submit']"
    a2_result_item: str = "[data-testid='note-item'], .note-item, li a"
    a3_item_select: str = "[name='item_id']"
    a3_type_select: str = "[name='type']"
    a3_qty_input: str = "[name='quantity']"
    a3_submit_button: str = "button[type='submit']"
    a3_history_trigger: str = "[data-testid='open-history'], a[href*='history']"


class PlaywrightUIDriver:
    """Optional Playwright-backed driver for isolated evaluation environments."""

    def __init__(
        self,
        base_url: str,
        selectors: PlaywrightSelectors | None = None,
        timeout_ms: int = 10_000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.selectors = selectors or PlaywrightSelectors()
        self.timeout_ms = timeout_ms

    @staticmethod
    def _import_sync_playwright():
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UIDriverUnavailableError(
                "Playwright is not installed in this evaluation environment."
            ) from exc
        return sync_playwright

    def run_a1_create_and_filter(
        self,
        *,
        title: str,
        status: str,
        due: str,
        filter_status: str,
    ) -> UIObservation:
        sync_playwright = self._import_sync_playwright()
        sel = self.selectors
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(self.base_url, wait_until="networkidle")
                page.fill(sel.a1_title_input, title)
                page.select_option(sel.a1_status_select, status)
                page.fill(sel.a1_due_input, due)
                page.click(sel.a1_submit_button)
                page.select_option(sel.a1_filter_select, filter_status)
                page.wait_for_load_state("networkidle")
                return UIObservation(visible_text=page.inner_text("body"), url=page.url)
            finally:
                browser.close()

    def run_a2_search_and_open(self, *, query: str) -> UIObservation:
        sync_playwright = self._import_sync_playwright()
        sel = self.selectors
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(self.base_url, wait_until="networkidle")
                page.fill(sel.a2_search_input, query)
                page.click(sel.a2_search_submit)
                page.wait_for_load_state("networkidle")
                page.locator(sel.a2_result_item).first.click()
                page.wait_for_load_state("networkidle")
                return UIObservation(visible_text=page.inner_text("body"), url=page.url)
            finally:
                browser.close()

    def run_a3_stock_in_and_view_history(
        self,
        *,
        item_name: str,
        quantity: int,
    ) -> UIObservation:
        sync_playwright = self._import_sync_playwright()
        sel = self.selectors
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(self.base_url, wait_until="networkidle")
                page.select_option(sel.a3_item_select, label=item_name)
                page.select_option(sel.a3_type_select, "nhập")
                page.fill(sel.a3_qty_input, str(quantity))
                page.click(sel.a3_submit_button)
                page.wait_for_load_state("networkidle")
                if page.locator(sel.a3_history_trigger).count() > 0:
                    page.locator(sel.a3_history_trigger).first.click()
                    page.wait_for_load_state("networkidle")
                return UIObservation(visible_text=page.inner_text("body"), url=page.url)
            finally:
                browser.close()
