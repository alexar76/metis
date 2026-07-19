// Metis load test (k6). Answers "will it hold under N concurrent callers?"
//
//   k6 run -e BASE=https://metis.modelmarket.dev deploy/loadtest.k6.js
//   k6 run -e BASE=http://127.0.0.1:8080 -e VUS=20 -e DURATION=2m deploy/loadtest.k6.js
//
// Mix: mostly cheap /health + fast-route /v1/verify; a small fraction of council runs
// (council is ~60-90s on a reasoning base, so keep its share low or it dominates wall-clock).
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE = __ENV.BASE || "http://127.0.0.1:8080";
const VUS = parseInt(__ENV.VUS || "10");
const DURATION = __ENV.DURATION || "1m";

const verifyLatency = new Trend("verify_latency_ms", true);
const errors = new Rate("errors");

export const options = {
  scenarios: {
    smoke_health: { executor: "constant-vus", vus: VUS, duration: DURATION, exec: "health" },
    fast_verify: { executor: "constant-vus", vus: Math.max(2, Math.floor(VUS / 2)), duration: DURATION, exec: "fastVerify" },
  },
  thresholds: {
    errors: ["rate<0.05"],                 // <5% errors
    "http_req_duration{scenario:smoke_health}": ["p(95)<500"],
    verify_latency_ms: ["p(95)<20000"],    // fast route p95 < 20s
  },
};

export function health() {
  const r = http.get(`${BASE}/health`);
  check(r, { "health 200": (x) => x.status === 200, "status ok": (x) => (x.json() || {}).status === "ok" });
  errors.add(r.status !== 200);
  sleep(1);
}

export function fastVerify() {
  const payload = JSON.stringify({ input: "What is 12 * 12? Answer with the number.", route: "fast" });
  const r = http.post(`${BASE}/v1/verify`, payload, { headers: { "Content-Type": "application/json" }, timeout: "60s" });
  verifyLatency.add(r.timings.duration);
  check(r, { "verify 200": (x) => x.status === 200, "has answer": (x) => !!(x.json() || {}).answer });
  errors.add(r.status !== 200);
  sleep(2);
}
