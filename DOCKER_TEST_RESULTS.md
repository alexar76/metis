# Docker E2E Test Results

**Date:** 2026-07-09  
**Version:** Metis v0.2.0  
**Environment:** macOS, Docker Compose v2

## Stack tested

```bash
docker compose -f docker-compose.yml config --quiet
docker compose build coordinator node-a node-b
```

| Service | Image | Health check | Status |
|---------|-------|--------------|--------|
| coordinator | metis:latest | `GET /health` | ✅ Config valid |
| node-a | metis:latest | `GET /health` | ✅ Config valid |
| node-b | metis:latest | `GET /health` | ✅ Config valid |

## Compose validation

- `docker-compose.yml` — coordinator + 2 worker nodes on `metis-net`
- `docker-compose.prod.yml` — production profile with read-only rootfs
- Config mounts: `config/docker-cluster.yaml`, `config/docker-runtime.yaml`
- Volumes: `metis-memory`, `metis-config`

## Health endpoint (v0.2)

`GET /health` returns:

```json
{
  "status": "ok",
  "service": "metis",
  "version": "0.2.0",
  "nodes": [],
  "circuit_breakers": [],
  "knowledge_entries": 0
}
```

With distributed config, `nodes` lists worker status from cluster registry.

## Known requirements

1. **API keys** — set in `.env` (not committed): `DEEPSEEK_API_KEY`, `METIS_API_KEY`
2. **Local models** — use `--profile local-models` for Ollama sidecar
3. **MCP** — ecosystem presets require separate package install in container

## Test commands

```bash
# Validate configs
metis config validate -c config/docker-runtime.yaml

# Unit tests (no Docker required)
pytest tests/test_docker_config.py -q

# Full stack (requires API keys in .env)
docker compose up -d
curl -sf http://localhost:8080/health | jq .
docker compose down
```

## Notes

- Read-only container filesystem with `tmpfs` on `/tmp` — trace and knowledge data persist via `metis-memory` volume
- Production mode sets `METIS_PRODUCTION=true` — Bearer auth required for `/v1/feedback` and `/v1/traces/{id}`
