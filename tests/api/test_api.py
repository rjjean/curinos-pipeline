"""
API-level validation tests.

API Verification Requirement:
  - Schema compliance (jsonschema)
  - HTTP response headers
  - Data accuracy (pagination math, sort correctness, sort stability)

These tests treat the server as a black box. They do not import app code —
that's deliberate, so the same tests can run against any deployment of the
same API contract.
"""
from __future__ import annotations
from jsonschema import Draft7Validator
import pytest


# ---------- Schema & headers ----------

def test_default_response_matches_schema(http, schema):
    resp = http.get("/api/records")
    assert resp.status_code == 200
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(resp.json()), key=lambda e: e.path)
    assert not errors, "Schema violations:\n" + "\n".join(
        f"  - {list(e.path)}: {e.message}" for e in errors
    )


def test_response_headers(http):
    resp = http.get("/api/records")
    assert resp.headers.get("content-type", "").startswith("application/json")
    # No-store is required because the reconciler must see fresh data on
    # every request — a cached stale page would cause UI/API drift that
    # looks like a real bug but isn't.
    assert "no-store" in resp.headers.get("cache-control", "").lower()


# ---------- Pagination math ----------

@pytest.mark.parametrize("limit", [5, 10, 25])
def test_pagination_arithmetic_is_consistent(http, limit):
    """First page tells us total; walking N pages should yield exactly that many records."""
    first = http.get("/api/records", params={"page": 1, "limit": limit}).json()
    total = first["pagination"]["total"]
    total_pages = first["pagination"]["total_pages"]
    assert total_pages == -(-total // limit), "total_pages must equal ceil(total/limit)"

    seen_ids: set[int] = set()
    for page in range(1, total_pages + 1):
        body = http.get("/api/records", params={"page": page, "limit": limit}).json()
        page_ids = [r["id"] for r in body["data"]]
        # No duplicates across pages, no gaps, full coverage of the dataset.
        assert not (seen_ids & set(page_ids)), f"Duplicate ids on page {page}"
        seen_ids.update(page_ids)
    assert len(seen_ids) == total, "Walked pages did not yield all records exactly once"


def test_page_beyond_last_returns_empty_data(http):
    body = http.get("/api/records", params={"page": 999, "limit": 10}).json()
    assert body["data"] == []
    # pagination.page still echoes what was asked — clients rely on this.
    assert body["pagination"]["page"] == 999


# ---------- Sort correctness ----------

@pytest.mark.parametrize("field,direction", [
    ("balance", "asc"),
    ("balance", "desc"),
    ("last_activity_date", "asc"),
    ("transaction_count", "desc"),
])
def test_sort_is_correct_and_stable(fetch_all_records, field, direction):
    """
    Walk the entire dataset under a sort spec and verify two properties:
      1. The sequence is correctly ordered on the primary key.
      2. On ties in the primary key, id ascends (stable tiebreaker).
    Without the tiebreaker check, a sort can look correct but still cause
    UI/API drift on equal-value rows.
    """
    records = fetch_all_records(sort=f"{field}:{direction}")
    for prev, curr in zip(records, records[1:]):
        if prev[field] == curr[field]:
            assert prev["id"] < curr["id"], (
                f"Sort instability on tie at {field}={prev[field]}: "
                f"id {prev['id']} appeared before {curr['id']}"
            )
        elif direction == "asc":
            assert prev[field] <= curr[field]
        else:
            assert prev[field] >= curr[field]


# ---------- Bad input ----------

@pytest.mark.parametrize("bad_sort", ["balance", "balance:sideways", "unknown:asc"])
def test_invalid_sort_returns_400(http, bad_sort):
    """Malformed sort specs are rejected. Empty string is NOT in this list —
    an empty query parameter is treated by the server as 'no sort specified',
    which is valid. (See AI Manifest, Failure 3.)"""
    resp = http.get("/api/records", params={"sort": bad_sort})
    assert resp.status_code in (400, 422), f"Expected 4xx for sort={bad_sort!r}"


def test_empty_sort_param_is_equivalent_to_no_sort(http):
    """An empty sort param should be treated as 'no sort', not as invalid input."""
    resp = http.get("/api/records", params={"sort": ""})
    assert resp.status_code == 200
    assert resp.json()["meta"]["sort"] is None


def test_negative_page_rejected(http):
    resp = http.get("/api/records", params={"page": 0})
    assert resp.status_code in (400, 422)
