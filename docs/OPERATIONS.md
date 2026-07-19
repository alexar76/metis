# Metis — operations runbook

Production concerns for running Metis as the ecosystem's cognition tier: **monitoring &
alerting**, **backup & disaster recovery**, and **load testing**. Honest status at the end.

## Monitoring & alerting

- **Metrics**: `GET /metrics` — Prometheus exposition (`text/plain; version=0.0.4`).
  Exposes `metis_up`, `metis_build_info`, `metis_knowledge_entries`,
  `metis_circuit_breaker_open{endpoint}` / `_failures{endpoint}`, and traced-run counters.
  **Internal only** — it is *not* proxied through nginx (don't leak metrics publicly); scrape
  it on the docker network (`metis:8080/metrics`) or `127.0.0.1:8080/metrics`.
- **Liveness**: `GET /health` (already polled by alien-monitor) — status, circuit breakers,
  knowledge count, cluster nodes.
- **Prometheus**: add a scrape job + load the alert rules:
  ```yaml
  scrape_configs:
    - job_name: metis
      metrics_path: /metrics
      static_configs: [{ targets: ["metis:8080"] }]
  rule_files: [ "deploy/monitoring/prometheus-alerts.yml" ]
  ```
- **Alerts** ([`deploy/monitoring/prometheus-alerts.yml`](deploy/monitoring/prometheus-alerts.yml)):
  `MetisDown` (up==0, 1m, **critical**), `MetisNoScrape` (target absent), `MetisProviderCircuitOpen`
  (an LLM/vision provider failing), `MetisKnowledgeStoreEmptied` (lost data mount). Route
  `severity: critical` to your pager (PagerDuty/OpsGenie/Alertmanager) so a Metis outage pages
  **you**, not your users.
- **Grafana**: import [`deploy/monitoring/grafana-dashboard.json`](deploy/monitoring/grafana-dashboard.json)
  (uid `metis-cognition`) — up, knowledge, breaker state, run/failure rates.

## Backup & disaster recovery

State that matters lives in the **`/app/data` bind-mount** (`/opt/metis/data` on the host):
knowledge store (SQLite), vector/episodic memory, traces. It is **not** rebuildable from the
image — back it up.

- **Snapshot + rotate**: [`deploy/backup.sh`](deploy/backup.sh) → `/opt/metis/backups/metis-data-<ts>.tar.gz`, keeps newest 14.
  ```cron
  30 3 * * *  /opt/metis/deploy/backup.sh >/var/log/metis-backup.log 2>&1
  ```
- **Restore**: `./deploy/backup.sh --restore /opt/metis/backups/metis-data-<ts>.tar.gz`
  (stops the container, rsyncs the snapshot, `chown 1000:1000`, restarts).
- **Rebuild from scratch** (total loss): recreate the container per
  [`deploy/README.md`](deploy/README.md), then re-seed grounding:
  `docker exec -i metis python3 - data/knowledge < scripts/seed_ecosystem_knowledge.py`.
- **Config**: `prod.yaml` holds the provider keys and is **git-excluded** — keep it in your
  secret store; it is the only piece not reproducible from the repo.

## Load testing

[`deploy/loadtest.k6.js`](deploy/loadtest.k6.js) (k6): a health + fast-route mix with SLO
thresholds (errors <5%, health p95 <500ms, fast-verify p95 <20s).
```bash
k6 run -e BASE=http://127.0.0.1:8080 -e VUS=20 -e DURATION=2m deploy/loadtest.k6.js
```
Note: the `council` route is intentionally ~60–90s on a reasoning base — load-test the `fast`
route for throughput; size `council` concurrency by provider rate limits, not by Metis.

## Honest status

| Concern | Status |
|---------|--------|
| Metrics endpoint | ✅ `/metrics` (Prometheus) |
| Dashboards | ✅ Grafana dashboard JSON (import) |
| Alerting rules | ✅ Prometheus rules; **you must wire your pager** (Alertmanager → PagerDuty/OpsGenie) |
| Backup | ✅ script + cron; **verify restores periodically** |
| DR plan | ✅ documented (restore + rebuild + re-seed) |
| Load test | ✅ k6 script + SLO thresholds; run it against a staging node before big Factory fan-out |
| Autoscaling / HA | ⚠️ single-node demo; the distributed coordinator exists but multi-node HA isn't wired here |
