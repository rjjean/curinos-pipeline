# Architecture

## Design principle

One process owns the pipeline. The orchestrator (`orchestrator/run_pipeline.py`)
is the only thing that knows about the whole lifecycle: server up, snapshot,
tests, load, server down, report. Every other component does one thing and
exposes a JSON artifact when it finishes. The report generator only reads
those artifacts; it never needs to know how they were produced.

This separation matters because it makes each layer testable and replaceable
in isolation. The API tests don't care whether they're invoked by the
orchestrator, by `pytest` directly, or by CI, they only need a base URL.
The orchestrator doesn't care what's inside `api.json`; it only cares
whether the phase exited zero.

## Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    orchestrator/run_pipeline.py                          │
│                       (single entry point)                               │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│ 1. Start AUT  │         │ 2. Snapshot   │         │ 3. Phase loop │
│               │ ──────► │               │ ──────► │               │
│ uvicorn       │         │ Walk all      │         │ api → ui →    │
│ FastAPI       │         │ pages, write  │         │ load          │
│ wait /healthz │         │ snapshot.json │         │               │
└───────────────┘         └───────────────┘         └───────────────┘
                                                            │
                                  ┌─────────────────────────┼─────────────────────────┐
                                  ▼                         ▼                         ▼
                          ┌───────────────┐         ┌───────────────┐         ┌───────────────┐
                          │ API phase     │         │ UI phase      │         │ Load phase    │
                          │               │         │               │         │               │
                          │ pytest        │         │ pytest +      │         │ k6 (optional) │
                          │ - schema      │         │ Playwright    │         │ - p95 < 500ms │
                          │ - headers     │         │ POM           │         │ - error < 1%  │
                          │ - pagination  │         │ - read rows   │         │               │
                          │ - sort        │         │ - assert ==   │         │ writes        │
                          │   stability   │         │   API payload │         │ load.json     │
                          │               │         │               │         │               │
                          │ writes        │         │ writes        │         │               │
                          │ api.json      │         │ ui.json       │         │               │
                          └───────────────┘         └───────────────┘         └───────────────┘
                                  │                         │                         │
                                  └─────────────────────────┼─────────────────────────┘
                                                            │
                                                            ▼
                                  ┌─────────────────────────────────────────────────┐
                                  │ 4. Stop AUT (always, via context manager)       │
                                  └─────────────────────────────────────────────────┘
                                                            │
                                                            ▼
                                  ┌─────────────────────────────────────────────────┐
                                  │ 5. report_generator.py                          │
                                  │    reads snapshot.json + api.json + ui.json +   │
                                  │    load.json → report.md + report.html          │
                                  └─────────────────────────────────────────────────┘
                                                            │
                                                            ▼
                                                exit 0 / non-zero  (CI gate)
```

## Component responsibilities

### Application Under Test (`app/`)

A small FastAPI service with a paginated/sortable `/api/records` endpoint
and a static UI (`/`) that renders the data as a table. The dataset is
deterministic (seeded RNG), so the same records are produced on every run —
this is essential for reconciliation tests where UI ↔ API equality is the
assertion.

Two design choices deserve calling out:

- **Stable sort with `id` tiebreaker.** Records with equal sort keys must
  resolve in a deterministic order, or the UI and API can produce different
  orderings of the same data and the reconciler fails on a false positive.
  The server always sorts by `id` ascending first, then applies the
  user-requested sort.
- **Raw stringified values in the UI.** The table renders `String(value)`
  for every cell rather than formatted output (`$1,234.56`). This makes
  reconciliation cheap and prevents formatting drift between UI and API
  from being silently invisible. A separate "display" layer would format —
  but that layer would also need its own validation tests.

### API tests (`tests/api/`)

Black-box tests against the running server. Cover the four data-quality
dimensions that matter for a table API:

- **Schema** — every response must match `record_schema.json` exactly.
  `additionalProperties: false` catches accidentally exposed fields.
- **Headers** — `content-type` and cache control. Cache must be off; a
  stale cached page would corrupt reconciliation in a way that looks
  like a real bug.
- **Pagination math** — walking all pages yields the dataset exactly once,
  no duplicates, no gaps, with `total_pages == ceil(total/limit)`.
- **Sort correctness and stability** — sequences are correctly ordered
  AND ties resolve consistently. The stability check is the one most
  often missed; without it, a pipeline can ship for months before the
  first equal-key collision exposes the bug.

### UI tests (`tests/ui/`)

Playwright drives a headless Chromium, opens the table, performs a state
change (set page size, paginate, sort), reads the rendered rows, and
asserts strict equality with the API payload produced by the same
parameters.

The Page Object Model (`pages/table_page.py`) is the only place that
knows DOM selectors. Tests express intent ("sort by balance descending"),
not mechanics ("click `th[data-sort=balance]` twice"). When the UI markup
changes, only the POM moves.

Tests wait on a `data-loaded` attribute the UI sets after every render
rather than sleeping for a fixed time. This is the single biggest source
of flakiness in AI-generated UI test code, and removing it removes the
flakiness.

### Load tests (`tests/load/`)

A short bounded k6 run with a realistic endpoint mix (most traffic is
small unsorted pages; some hits sorted endpoints; some hits deeper pages).
Thresholds are assertions — k6 exits non-zero if `p95 >= 500ms` or if
error rate exceeds 1%, so the orchestrator gates the pipeline on
performance without parsing any output itself.

k6 is optional. If it's not installed, the load phase logs a skip and
the rest of the pipeline still runs. This matters for the demo: the
reviewer can run `make all` without a separate k6 install and still
get a complete signal on the other three phases.

### Orchestrator (`orchestrator/`)

Two files:

- **`run_pipeline.py`** owns the entire lifecycle. It starts uvicorn as a
  subprocess, waits for `/healthz`, runs each phase, and tears the server
  down — even on crash or Ctrl-C — using a context manager. Phase
  outcomes are collected and written to `pipeline_summary.json`. The
  process exits non-zero if any phase failed, so it can be used directly
  as a CI gate.
- **`report_generator.py`** reads the per-phase JSON artifacts and emits
  a single Markdown report plus a basic HTML version. The report shows
  pass/fail per phase, summary metrics, the first line of any failure,
  and pointers to the raw artifacts.

## Decisions made and rejected

- **Why Playwright over Selenium.** Playwright's auto-waiting and built-in
  test runner produce dramatically less flaky tests with less code. The JD
  lists both as acceptable; Playwright is the lower-risk choice for a
  reconciler where flakiness is indistinguishable from a real defect.
- **Why a local AUT over a public API.** A public API can change schema,
  rate-limit a load test, or go down on submission day. Building a
  controlled AUT means the reviewer can `git clone` and run with zero
  external dependencies. The cost is one small server's worth of code,
  which doubles as a demonstration that you understand both sides of the
  contract you're testing.
- **Why Makefile over a Python CLI.** A Makefile is the universal "single
  command" for engineering reviewers and no extra install, no entry-point
  registration. A Python CLI (Click, Typer) would be nicer for larger
  surface area; for `make all` and `make clean`, Make is enough.
- **Why pytest-json-report over JUnit XML.** Native JSON consumption by
  the report generator is simpler and less brittle than parsing XML.
  JUnit would be the right choice for integration with external CI
  dashboards (Jenkins/Allure); this pipeline owns its own reporting.
