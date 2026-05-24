"""
FastAPI server: Application Under Test.

Exposes:
  GET /api/records  — paginated, sortable JSON records (the API surface to validate)
  GET /             — static HTML UI that consumes the API (the UI surface to validate)
  GET /healthz      — health check for the orchestrator to wait on

Design notes:
  - Sorting is stable: when sort keys tie, records fall back to id ascending.
    This is deliberate — without a stable tiebreaker, UI and API ordering can
    diverge on equal keys, which would break the reconciliation tests for the
    wrong reason. (Sort stability is the #1 thing AI tools get wrong here.)
  - The response envelope (data + pagination + meta) mirrors common REST
    patterns and is what the jsonschema in tests/schemas validates against.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.data import RECORDS

app = FastAPI(title="Curinos Validation Pipeline — AUT", version="1.0.0")

_VALID_SORT_FIELDS = {
    "id", "account_id", "tier", "region", "product_line",
    "balance", "transaction_count", "last_activity_date", "is_active",
}
_VALID_DIRECTIONS = {"asc", "desc"}

# Allow generous browser caching to be defeated by tests; keep cache off.
_NO_CACHE_HEADERS = { "Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache",}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "record_count": len(RECORDS)}


@app.get("/api/records")
def get_records(
    page: int = Query(1, ge=1, description="1-indexed page number"),
    limit: int = Query(10, ge=1, le=100, description="Records per page"),
    sort: Optional[str] = Query(
        None,
        description="Sort spec as 'field:direction', e.g. 'balance:desc'. "
                    "Tiebreaker is always id ascending (stable sort).",
    ),
) -> JSONResponse:
    """Return a paginated, optionally sorted slice of the dataset."""
    sort_field: Optional[str] = None
    sort_direction: str = "asc"

    if sort:
        parts = sort.split(":")
        if len(parts) != 2:
            raise HTTPException(400, detail="Invalid sort format. Use 'field:direction'.")
        sort_field, sort_direction = parts[0], parts[1].lower()
        if sort_field not in _VALID_SORT_FIELDS:
            raise HTTPException(400, detail=f"Unknown sort field: {sort_field}")
        if sort_direction not in _VALID_DIRECTIONS:
            raise HTTPException(400, detail="Sort direction must be 'asc' or 'desc'.")

    working = sorted(RECORDS, key=lambda r: r["id"])
    if sort_field:
        working = sorted(
            working,
            key=lambda r: r[sort_field],
            reverse=(sort_direction == "desc"),
        )

    total = len(working)
    total_pages = (total + limit - 1) // limit
    start = (page - 1) * limit
    end = start + limit
    page_records = working[start:end]

    payload = {
        "data": page_records,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
        },
        "meta": {
            "sort": sort if sort_field else None,
        },
    }
    return JSONResponse(content=payload, headers=_NO_CACHE_HEADERS)


# Serve the static UI at /. Mounted last so /api/* routes win.
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
