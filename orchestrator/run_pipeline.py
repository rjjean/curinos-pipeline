"""
Pipeline orchestrator.

A single Python process that owns the entire validation run:
  1. Starts the AUT in a subprocess and waits for /healthz to be reachable.
  2. Snapshots the full dataset from the API (the source-of-truth baseline).
  3. Runs the API test suite (pytest).
  4. Runs the UI reconciliation suite (pytest + Playwright).
  5. Runs the k6 load test if k6 is installed; gracefully skips otherwise.
  6. Stops the server.
  7. Hands the collected artifacts to report_generator.

Design choices:
  - Subprocess management is explicit (Popen + terminate on exit) rather than
    via shell backgrounding, so we always clean up, even on Ctrl-C or test
    crash. A leaked uvicorn would cause the next run to fail mysteriously.
  - Each phase writes a JSON artifact to reports/, even on failure, so the
    final report can show partial outcomes instead of going dark.
  - The orchestrator's exit code is the OR of phase outcomes: any failure
    fails the whole pipeline. This is what makes it usable as a CI gate.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
HOST = "127.0.0.1"
PORT = int(os.environ.get("AUT_PORT", "8000"))
BASE_URL = f"http://{HOST}:{PORT}"


# ---------- subprocess plumbing ----------

def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


@contextmanager
def start_server():
    """Start uvicorn, wait for /healthz, terminate cleanly on exit."""
    if not _port_is_free(HOST, PORT):
        print(f"[orchestrator] Port {PORT} already in use; assuming server is up.")
        yield None
        return

    print(f"[orchestrator] Starting AUT on {BASE_URL} ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", HOST, "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_health(timeout_s=15)
        yield proc
    finally:
        print("[orchestrator] Stopping AUT ...")
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_for_health(timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/healthz", timeout=2.0)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"AUT failed to become healthy at {BASE_URL}")


# ---------- phases ----------

def phase_snapshot() -> dict:
    """Pull the entire dataset; record metadata. This is the integrity anchor."""
    print("[orchestrator] Phase: dataset snapshot")
    records: list[dict] = []
    page = 1
    while True:
        r = httpx.get(f"{BASE_URL}/api/records",
                      params={"page": page, "limit": 100}, timeout=10.0)
        r.raise_for_status()
        body = r.json()
        records.extend(body["data"])
        if page >= body["pagination"]["total_pages"]:
            break
        page += 1

    snapshot_path = REPORTS / "snapshot.json"
    snapshot_path.write_text(json.dumps(records, indent=2))
    print(f"[orchestrator]   captured {len(records)} records → {snapshot_path}")
    return {"phase": "snapshot", "passed": True, "record_count": len(records)}


def phase_pytest(label: str, target: str) -> dict:
    """Run a pytest suite; persist JSON output via pytest-json-report."""
    print(f"[orchestrator] Phase: {label}")
    json_path = REPORTS / f"{label}.json"
    cmd = [
        sys.executable, "-m", "pytest", target,
        "--json-report", f"--json-report-file={json_path}",
        "-q", "--no-header",
    ]
    env = os.environ.copy()
    env["AUT_BASE_URL"] = BASE_URL
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    passed = result.returncode == 0
    print(f"[orchestrator]   {label}: {'PASS' if passed else 'FAIL'}")
    return {"phase": label, "passed": passed, "report": str(json_path)}


def phase_load() -> dict:
    """Run k6 load test if installed; skip cleanly if not."""
    print("[orchestrator] Phase: load test (k6)")
    if not shutil.which("k6"):
        print("[orchestrator]   k6 not found on PATH — skipping load phase.")
        return {"phase": "load", "passed": True, "skipped": True}

    summary_path = REPORTS / "load.json"
    cmd = ["k6", "run",
           "--summary-export", str(summary_path),
           "--quiet",
           str(ROOT / "tests" / "load" / "load_test.js")]
    env = os.environ.copy()
    env["BASE_URL"] = BASE_URL
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    passed = result.returncode == 0
    print(f"[orchestrator]   load: {'PASS' if passed else 'FAIL'}")
    return {"phase": "load", "passed": passed, "report": str(summary_path)}


# ---------- entry ----------

def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    results: list[dict] = []

    with start_server():
        results.append(phase_snapshot())
        results.append(phase_pytest("api", "tests/api"))
        results.append(phase_pytest("ui", "tests/ui"))
        results.append(phase_load())

    # Persist aggregated results for the report generator.
    summary_path = REPORTS / "pipeline_summary.json"
    summary_path.write_text(json.dumps(results, indent=2))

    # Hand off to report generator.
    print("[orchestrator] Generating consolidated report ...")
    subprocess.run([sys.executable, "-m", "orchestrator.report_generator"], cwd=ROOT)

    # Any phase failure fails the whole pipeline.
    all_passed = all(r.get("passed", False) for r in results)
    print(f"[orchestrator] Pipeline: {'PASS' if all_passed else 'FAIL'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
