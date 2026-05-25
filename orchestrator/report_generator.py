"""
Consolidated report generator.

Reads the per-phase JSON artifacts the orchestrator dropped in reports/
and produces a single human-readable Markdown report plus a basic HTML
version. The goal is one document you can read top to bottom and know 
whether the data pipeline is healthy.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _pytest_summary(pytest_json: dict | None) -> str:
    if not pytest_json:
        return "_no report_"
    s = pytest_json.get("summary", {})
    total = s.get("total", 0)
    passed = s.get("passed", 0)
    failed = s.get("failed", 0)
    duration = pytest_json.get("duration", 0)
    return f"{passed}/{total} passed, {failed} failed ({duration:.1f}s)"


def _pytest_failures(pytest_json: dict | None) -> list[str]:
    if not pytest_json:
        return []
    lines: list[str] = []
    for test in pytest_json.get("tests", []):
        if test.get("outcome") == "failed":
            lines.append(f"  - `{test['nodeid']}`")
            longrepr = test.get("call", {}).get("longrepr", "")
            if longrepr:
                first = longrepr.splitlines()[0] if longrepr else ""
                lines.append(f"    > {first}")
    return lines


def _k6_summary(load_json: dict | None) -> str:
    if not load_json:
        return "_no load report_"
    metrics = load_json.get("metrics", {})
    dur = metrics.get("http_req_duration", {}).get("values", {})
    failed = metrics.get("http_req_failed", {}).get("values", {})
    p95 = dur.get("p(95)")
    avg = dur.get("avg")
    fail_rate = failed.get("rate", 0)
    p95_str = f"{p95:.1f}ms" if p95 is not None else "n/a"
    avg_str = f"{avg:.1f}ms" if avg is not None else "n/a"
    return f"p95={p95_str}, avg={avg_str}, error rate={fail_rate:.2%}"


def build_report() -> str:
    summary = _load_json(REPORTS / "pipeline_summary.json") or []
    api_json = _load_json(REPORTS / "api.json")
    ui_json = _load_json(REPORTS / "ui.json")
    load_json = _load_json(REPORTS / "load.json")
    snapshot = _load_json(REPORTS / "snapshot.json")

    snapshot_count = len(snapshot) if isinstance(snapshot, list) else "n/a"
    overall_pass = all(p.get("passed", False) for p in summary) if summary else False
    overall = "PASS ✅" if overall_pass else "FAIL ❌"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# Data Health Report",
        f"",
        f"**Generated:** {ts}",
        f"**Overall:** {overall}",
        f"**Dataset snapshot:** {snapshot_count} records",
        f"",
        f"## Phase results",
        f"",
        f"| Phase | Result | Summary |",
        f"|---|---|---|",
        f"| Snapshot | {'PASS' if (summary and summary[0].get('passed')) else 'FAIL'} | {snapshot_count} records captured |",
        f"| API tests | {_pytest_summary(api_json).split(' ')[0]} | {_pytest_summary(api_json)} |",
        f"| UI reconciliation | {_pytest_summary(ui_json).split(' ')[0]} | {_pytest_summary(ui_json)} |",
        f"| Load test | {'PASS' if (load_json or _was_skipped(summary, 'load')) else 'FAIL'} | {_k6_summary(load_json) if load_json else 'skipped (k6 not installed)'} |",
        f"",
    ]

    api_failures = _pytest_failures(api_json)
    ui_failures = _pytest_failures(ui_json)
    if api_failures or ui_failures:
        lines.append("## Failures")
        lines.append("")
        if api_failures:
            lines.append("### API")
            lines.extend(api_failures)
            lines.append("")
        if ui_failures:
            lines.append("### UI reconciliation")
            lines.extend(ui_failures)
            lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    for name in ("snapshot.json", "api.json", "ui.json", "load.json", "pipeline_summary.json"):
        path = REPORTS / name
        marker = "✓" if path.exists() else "—"
        lines.append(f"- {marker} `reports/{name}`")
    lines.append("")
    return "\n".join(lines)


def _was_skipped(summary: list[dict], phase: str) -> bool:
    return any(p.get("phase") == phase and p.get("skipped") for p in summary)


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    md = build_report()
    (REPORTS / "report.md").write_text(md)
    # Simple HTML wrapper for browser viewing.
    html = (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Data Health Report</title>"
        "<style>body{font-family:system-ui;max-width:900px;margin:2rem auto;padding:0 1rem;}"
        "table{border-collapse:collapse;width:100%;}"
        "th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;}"
        "th{background:#f3f3f3;}code{background:#f4f4f4;padding:2px 4px;}</style>"
        "<pre style='white-space:pre-wrap'>" + md + "</pre>"
    )
    (REPORTS / "report.html").write_text(html)
    print(f"\n{md}\n")
    print(f"[report] Markdown: {REPORTS / 'report.md'}")
    print(f"[report] HTML:     {REPORTS / 'report.html'}")


if __name__ == "__main__":
    main()
