"""
UI and API reconciliation suite.

For each meaningful UI state (default load, custom page size, sorted column,
paginated forward), we:
  1. Read what the UI is showing.
  2. Call the same API the UI calls, with the same parameters.
  3. Assert the two are exactly equal; field by field, row by row.

This is the core "Data Reconciler" the challenge asks for. Equality is
strict: int vs float matters, boolean vs string matters. Any drift between
UI rendering and backend truth is a real bug in either the API, the UI,
or the rendering code, all of which this suite is meant to catch.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from tests.ui.pages.table_page import TablePage


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _api_records(http, page: int, limit: int, sort: str | None = None) -> list[dict]:
    params: dict = {"page": page, "limit": limit}
    if sort:
        params["sort"] = sort
    resp = http.get("/api/records", params=params)
    resp.raise_for_status()
    return resp.json()["data"]


def _assert_exact_match(ui_rows: list[dict], api_rows: list[dict]) -> None:
    assert len(ui_rows) == len(api_rows), (
        f"Row count mismatch — UI shows {len(ui_rows)}, API returns {len(api_rows)}"
    )
    mismatches = []
    for i, (ui_row, api_row) in enumerate(zip(ui_rows, api_rows)):
        if ui_row != api_row:
            diff_fields = {
                k: (ui_row.get(k), api_row.get(k))
                for k in set(ui_row) | set(api_row)
                if ui_row.get(k) != api_row.get(k)
            }
            mismatches.append(f"  row {i} (id={api_row.get('id')}): {diff_fields}")
    assert not mismatches, "UI ↔ API mismatches found:\n" + "\n".join(mismatches)


# ---- tests ----

def test_default_load_matches_api(browser_page, base_url, http):
    ui = TablePage(browser_page, base_url).open()
    ui_rows = ui.read_visible_rows()
    api_rows = _api_records(http, page=1, limit=10)
    _assert_exact_match(ui_rows, api_rows)


@pytest.mark.parametrize("size", [5, 25])
def test_custom_page_size_matches_api(browser_page, base_url, http, size):
    ui = TablePage(browser_page, base_url).open()
    ui.set_page_size(size)
    ui_rows = ui.read_visible_rows()
    api_rows = _api_records(http, page=1, limit=size)
    _assert_exact_match(ui_rows, api_rows)


@pytest.mark.parametrize("field,direction", [
    ("balance", "desc"),
    ("last_activity_date", "asc"),
    ("tier", "asc"),
])
def test_sorted_view_matches_api(browser_page, base_url, http, field, direction):
    ui = TablePage(browser_page, base_url).open()
    ui.sort_by(field, direction)
    ui_rows = ui.read_visible_rows()
    api_rows = _api_records(http, page=1, limit=10, sort=f"{field}:{direction}")
    _assert_exact_match(ui_rows, api_rows)


def test_paginated_forward_matches_api(browser_page, base_url, http):
    ui = TablePage(browser_page, base_url).open()
    ui.click_next()
    ui.click_next()
    ui_rows = ui.read_visible_rows()
    api_rows = _api_records(http, page=3, limit=10)
    _assert_exact_match(ui_rows, api_rows)
