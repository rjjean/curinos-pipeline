"""
Page Object Model for the records table.

The POM is the layer of indirection between test intent and 
DOM specifics. When markup changes, only this file moves — 
test_ui_reconciler.py doesn't need to.

All locators use data-testid or data-* attributes intentionally exposed
by the UI as a stable testing contract. CSS class or text selectors would
break on cosmetic changes; these don't.
"""
from __future__ import annotations
from typing import Any, Dict, List
from playwright.sync_api import Page, expect


# Same field set the UI renders, in the same column order.
COLUMNS = [
    "id", "account_id", "tier", "region", "product_line",
    "balance", "transaction_count", "last_activity_date", "is_active",
]


class TablePage:
    """Wraps the table UI for test interactions."""

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url

    # ---- navigation ----

    def open(self) -> "TablePage":
        self.page.goto(self.base_url)
        self._wait_for_loaded()
        return self

    # ---- actions ----

    def set_page_size(self, size: int) -> None:
        self.page.locator("[data-testid=limit-select]").select_option(str(size))
        self._wait_for_loaded()

    def click_next(self) -> None:
        self.page.locator("[data-testid=next-btn]").click()
        self._wait_for_loaded()

    def click_prev(self) -> None:
        self.page.locator("[data-testid=prev-btn]").click()
        self._wait_for_loaded()

    def sort_by(self, field: str, direction: str = "asc") -> None:
        """
        Click the column header until the indicator matches the desired direction.

        The UI toggles asc→desc on repeat clicks of the active column; from
        any other state, one click activates asc. So we may need 1 or 2 clicks.
        """
        if field not in COLUMNS:
            raise ValueError(f"Unknown sort field: {field}")
        header = self.page.locator(f"[data-testid=header-{field}]")
        # Force up to two clicks to reach the desired direction.
        for _ in range(2):
            current = header.get_attribute("class") or ""
            if direction == "asc" and "sorted-asc" in current:
                return
            if direction == "desc" and "sorted-desc" in current:
                return
            header.click()
            self._wait_for_loaded()
        # Final assertion in case neither state was reached.
        expect(header).to_have_class(
            f"sorted-{direction}", timeout=2000
        ) if direction in ("asc", "desc") else None

    # ---- reads ----

    def get_page_info_text(self) -> str:
        return self.page.locator("[data-testid=page-info]").inner_text()

    def read_visible_rows(self) -> List[Dict[str, Any]]:
        """
        Read every cell of every visible row into native Python values.

        Critical: the UI renders raw stringified values (no formatting). We
        cast each cell back to the type the API would return. If the UI ever
        starts formatting values (currency symbols, thousands separators),
        this is where the reconciler will fail loudly — and that's the right
        behavior, because UI-side formatting is exactly the kind of silent
        drift this whole pipeline exists to catch.
        """
        rows = self.page.locator("[data-testid=records-tbody] tr").all()
        out: List[Dict[str, Any]] = []
        for row in rows:
            record: Dict[str, Any] = {}
            for field in COLUMNS:
                text = row.locator(f"td[data-field={field}]").inner_text()
                record[field] = _cast(field, text)
            out.append(record)
        return out

    # ---- internals ----

    def _wait_for_loaded(self) -> None:
        """
        Wait for the in-flight render to settle.

        The UI sets data-loaded=true on tbody after every refresh. Using this
        instead of an arbitrary sleep eliminates the most common source of
        flaky UI tests (the AI-generated 'time.sleep(2)' anti-pattern).
        """
        tbody = self.page.locator("[data-testid=records-tbody]")
        expect(tbody).to_have_attribute("data-loaded", "true", timeout=5000)


def _cast(field: str, text: str) -> Any:
    """Cast cell text back to the type the API exposes."""
    if field in ("id", "transaction_count"):
        return int(text)
    if field == "balance":
        return float(text)
    if field == "is_active":
        return text == "true"
    return text
