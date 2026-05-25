# Curinos Validation Pipeline

A self-contained, end-to-end automated data-validation pipeline for a paginated/sortable
table application. Built for the Curinos QA Engineer technical challenge.

The pipeline orchestrates four concerns into one command:

1. **API verification** — schema, headers, pagination math, sort correctness & stability
2. **UI reconciliation** — Playwright reads the rendered table and asserts 100% exact match against the API payload that produced it
3. **Performance baseline** — k6 load test asserting p95 < 500ms under concurrent traffic
4. **Consolidated reporting** — a single Markdown + HTML health report

## Run

```bash
make all
```

That's the whole submission. `make all` installs Python deps, installs Playwright's Chromium,
launches the AUT, runs the snapshot + API + UI + load phases, generates `reports/report.md`,
and exits non-zero on any failure.

### Requirements

- Python 3.10+
- [k6](https://k6.io/docs/get-started/installation/) (optional — pipeline skips load phase if absent)

### Targets

| Command | What it does |
|---|---|
| `make all` | Setup + run (default) |
| `make setup` | Install Python deps, Playwright Chromium, and k6 |
| `make setup-python` | Install Python deps and Playwright Chromium only |
| `make setup-k6` | Install k6 only |
| `make run` | Run the orchestrator (assumes deps installed) |
| `make report` | Print the latest report |
| `make clean` | Wipe `reports/` |

## Repository layout

```
.
├── app/                      The Application Under Test (FastAPI + static UI)
│   ├── server.py             /api/records endpoint; serves the static UI
│   ├── data.py               Deterministic seeded synthetic dataset
│   └── static/               Minimal HTML/JS table with stable data-testid hooks
├── tests/
│   ├── conftest.py           Shared fixtures (base URL, schema, HTTP client)
│   ├── schemas/              jsonschema for the API response
│   ├── api/test_api.py       Schema, headers, pagination, sort correctness & stability
│   ├── ui/
│   │   ├── pages/table_page.py     Page Object Model for the table
│   │   └── test_ui_reconciler.py   UI ↔ API exact-match reconciliation
│   └── load/load_test.js     k6 load script (thresholds gate the build)
├── orchestrator/
│   ├── run_pipeline.py       Server lifecycle + phase sequencing + exit code
│   └── report_generator.py   Aggregates JSON artifacts → report.md + report.html
├── reports/                  Generated artifacts (gitignored)
├── .github/workflows/        Same pipeline as a CI job
├── Makefile                  Single-command entry point
└── requirements.txt
```

## Sample output

After `make all`, `reports/report.md` looks roughly like:

```
# Data Health Report
Generated: 2026-05-21 14:02:11 UTC
Overall: PASS ✅
Dataset snapshot: 75 records

## Phase results
| Phase             | Result | Summary                              |
|-------------------|--------|--------------------------------------|
| Snapshot          | PASS   | 75 records captured                  |
| API tests         | PASS   | 14/14 passed, 0 failed (1.8s)        |
| UI reconciliation | PASS   | 7/7 passed, 0 failed (12.4s)         |
| Load test         | PASS   | p95=78.2ms, avg=31.5ms, error=0.00%  |