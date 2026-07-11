# Docker End-to-End Test Results

**Date:** 2026-07-09  
**Host:** macOS (Docker Desktop 29.2.1)  
**Stack:** coordinator + node-a + node-b (no Ollama/redis profiles)

## Environment

- `.env` loaded from repo root (not committed): `DEEPSEEK_API_KEY`, `LMSTUDIO_*`, `METIS_API_KEY`, `METIS_NODE_A_KEY`, `METIS_NODE_B_KEY`
- **node-a** → LM Studio on host via `host.docker.internal:1234` (`microsoft/phi-4-reasoning-plus`)
- **node-b** → DeepSeek API (`deepseek-v4-flash`, `deepseek-v4-pro`)

## Docker daemon

```
docker info — OK (Docker Desktop, context: desktop-linux)
```

## Build

| Step | Result |
|------|--------|
| `docker compose build` | OK after restoring `pyproject.toml` (was truncated to coverage-only, causing `metis-coordinator: not found`) |
| Parallel build race | Intermittent `image already exists` when building all services; `docker compose build coordinator` works |

## Container health

```
NAME                STATUS
metis-coordinator   Up (healthy)   0.0.0.0:8080->8080/tcp
metis-node-a        Up (healthy)   8443 (internal)
metis-node-b        Up (healthy)   8444 (internal)
```

Cluster check from coordinator:

```
Coordinator: http://coordinator:8080
Healthy: 2/2
  [healthy] node-a @ http://node-a:8443 (~18ms)
  [healthy] node-b @ http://node-b:8444 (~3ms)
```

## API tests

| Endpoint | Auth | Result |
|----------|------|--------|
| `GET /health` | none | `{"status":"healthy","service":"coordinator","production":true,"distributed":true}` |
| `GET /v1/models` | Bearer `METIS_API_KEY` | Lists `metis`, `metis-fast`, `metis-thinking`, `metis-council`, `metis-agent` |
| `POST /v1/chat/completions` `metis-fast` | Bearer | **PASS** — answer `4` (~13s) |
| `POST /v1/chat/completions` `metis-council` | Bearer | **PASS** — answer `4` (~230s; council pipeline + LM Studio parser) |
| `POST /v1/query` | Bearer | **SLOW** — default `council` route exceeds 120s; use `POST /v1/chat/completions` with `metis-fast` for quick checks |

### Sample: `metis-fast`

```json
{
  "model": "metis-fast",
  "choices": [{"message": {"content": "4"}}],
  "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
}
```

### Sample: `metis-council`

```json
{
  "model": "metis-council",
  "choices": [{"message": {"content": "4"}}]
}
```

## Node RPC tests

| Node | Backend | `POST /metis/invoke` | Sample |
|------|---------|----------------------|--------|
| node-a | LM Studio | **PASS** (~17s) | `{"content":"4","model":"microsoft/phi-4-reasoning-plus"}` |
| node-b | DeepSeek | **PASS** (~2s) | `{"content":"4","model":"deepseek-v4-flash"}` |

## Fixes applied during test

1. **Restored `pyproject.toml`** — file contained only `[tool.coverage.*]`; Docker wheel installed `metis-0.0.0` without console scripts or dependencies.
2. **Node upstream API keys** — added `llm_api_key_env` in node YAML + `metis/distributed/cli.py` / `server.py` so node auth (`METIS_NODE_*_KEY`) is separate from LLM keys (`LMSTUDIO_API_KEY`, `DEEPSEEK_API_KEY`).
3. **FastAPI `Request` injection** — moved `from starlette.requests import Request` to module level in `server.py` (`from __future__ import annotations` broke invoke/health with 422).
4. **Coordinator OpenAI routes** — wired `openai_compat` router into `coordinator_server.py` (`/v1/models`, `/v1/chat/completions`).
5. **Docker configs** — updated `docker-node-*.yaml`, `docker-cluster.yaml`, `docker-runtime.yaml` for hybrid LM Studio + DeepSeek (synthesizer on node-b to avoid 120s LM Studio timeout).

## Known issues / notes

- **Council latency:** `metis-council` can take 3–4 minutes when parser_a hits local LM Studio; acceptable for smoke test.
- **First `metis-council` attempt** failed with 120s `ReadTimeout` on synthesizer via node-a; fixed by routing synthesizer to node-b (DeepSeek).
- **`metis-cluster status`** — CLI is `metis-cluster -c <cluster.yaml>` (no `status` subcommand).
- **Legacy env:** entrypoints map `SUPERBRAIN_*` / `COGNITIVE_*` → `METIS_*` (verified in scripts, not exercised).
- **Secrets:** API keys only in `.env`; not committed.

## Cleanup

Containers left **running and healthy** after successful tests.

```bash
# To stop:
docker compose -f /Users/alex/Projects/metis/docker-compose.yml down
```
