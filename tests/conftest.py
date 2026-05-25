"""
Shared pytest fixtures for API and UI test suites.

The server is managed by the orchestrator process; tests only get its URL.
This keeps tests stateless — they make no assumptions about how the server
is started, only that it's reachable. That matters because the same tests
should pass when invoked under CI, under the orchestrator, or by hand.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import httpx
import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def base_url() -> str:
    """The URL of the running AUT. Defaults to localhost:8000 for local runs."""
    return os.environ.get("AUT_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def schema() -> dict:
    schema_path = ROOT / "tests" / "schemas" / "record_schema.json"
    with schema_path.open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def http(base_url: str) -> httpx.Client:
    """Shared HTTP client. Verifies the server is reachable before tests run."""
    client = httpx.Client(base_url=base_url, timeout=10.0)
    try:
        r = client.get("/healthz")
        r.raise_for_status()
    except Exception as e:
        pytest.exit(f"AUT not reachable at {base_url}: {e}", returncode=2)
    yield client
    client.close()


@pytest.fixture
def fetch_all_records(http: httpx.Client):
    """
    Fetch the complete dataset by paging through /api/records.

    Used by reconciliation tests where we want the full backend truth to
    compare UI slices against. Page size 100 is the server's max.
    """
    def _fetch(sort: str | None = None) -> list[dict]:
        all_records: list[dict] = []
        page = 1
        while True:
            params: dict = {"page": page, "limit": 100}
            if sort:
                params["sort"] = sort
            resp = http.get("/api/records", params=params)
            resp.raise_for_status()
            body = resp.json()
            all_records.extend(body["data"])
            if page >= body["pagination"]["total_pages"]:
                break
            page += 1
        return all_records
    return _fetch
