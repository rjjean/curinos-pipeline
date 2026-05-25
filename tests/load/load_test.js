// k6 load test for the records API.
//
// Stages: 30s ramp to 20 VUs, 30s sustain, 10s ramp down. Short and bounded
// so it fits inside the orchestrated pipeline. Tune VUs/duration for harder
// stress runs via CLI flags (e.g. --vus 50 --duration 2m).
//
// Thresholds are assertions — k6 exits non-zero if a threshold is breached.
// That's how the orchestrator knows a perf regression has occurred without
// any extra parsing.

import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";

export const options = {
  stages: [
    { duration: "30s", target: 20 },
    { duration: "30s", target: 20 },
    { duration: "10s", target: 0 },
  ],
  thresholds: {
    // The example threshold: p95 < 500ms under concurrent load.
    "http_req_duration": ["p(95)<500"],
    // No 5xx; no 4xx beyond the intentional bad-input test in api tests.
    "http_req_failed": ["rate<0.01"],
  },
  summaryTrendStats: ["min", "med", "avg", "p(90)", "p(95)", "max"],
};

// Realistic mix: most traffic is small unsorted pages; some is sorted; some
// hits deeper pages. This catches perf regressions that only show under
// realistic access patterns rather than uniform one-pattern load.
function pickEndpoint() {
  const r = Math.random();
  if (r < 0.5)  return `/api/records?page=1&limit=10`;
  if (r < 0.75) return `/api/records?page=3&limit=25`;
  if (r < 0.9)  return `/api/records?sort=balance:desc&page=1&limit=10`;
  return `/api/records?sort=last_activity_date:asc&page=2&limit=25`;
}

export default function () {
  const url = `${BASE_URL}${pickEndpoint()}`;
  const res = http.get(url);
  check(res, {
    "status is 200":            (r) => r.status === 200,
    "response has data array":  (r) => Array.isArray(r.json("data")),
  });
  sleep(0.5 + Math.random() * 0.5);
}
