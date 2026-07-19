# Metis API Reference

**Version 0.2.0** · OpenAI-compatible HTTP API for the Metis cognitive runtime

Metis is **API-only** — no bundled chat UI. Clients connect via `POST /v1/chat/completions`, the Python `Metis` class, or the `metis` CLI. Use VS Code Continue, Cursor, or `curl` against the serve endpoint.

---

## Table of Contents

1. [Base URL](#base-url)
2. [Authentication](#authentication)
3. [Endpoints](#endpoints)
   - [GET /health](#get-health)
   - [POST /v1/feedback](#post-v1feedback)
   - [GET /v1/traces/{trace_id}](#get-v1tracestrace_id)
   - [GET /v1/models](#get-v1models)
   - [POST /v1/chat/completions](#post-v1chatcompletions)
4. [Models](#models)
5. [Request Schema](#request-schema)
6. [Response Schema](#response-schema)
7. [Streaming (SSE)](#streaming-sse)
8. [Error Responses](#error-responses)
9. [Examples](#examples)
10. [Related Documentation](#related-documentation)

---

## Base URL

| Deployment | URL |
|------------|-----|
| Local development | `http://localhost:8080` |
| Docker coordinator | `http://localhost:8080` (or `METIS_COORDINATOR_PORT`) |

All OpenAI-compatible routes are under `/v1`.

---

## Authentication

Bearer token authentication is enforced when **either**:

- `METIS_PRODUCTION=true` (or `SUPERBRAIN_PRODUCTION` / `COGNITIVE_PRODUCTION`), **or**
- `METIS_API_KEY` is set in the environment

```http
Authorization: Bearer sk-your-secret-key
```

| Environment variable | Accepted aliases |
|---------------------|------------------|
| `METIS_API_KEY` | `SUPERBRAIN_API_KEY`, `COGNITIVE_API_KEY` |

| Mode | Behavior |
|------|----------|
| Development (no key, not production) | Auth optional — requests proceed without `Authorization` |
| Production or key configured | `401` without valid Bearer token |
| Production without key set | `500` — `METIS_API_KEY must be set in production mode` |

---

## Endpoints

### GET /health

Service health probe. **No authentication required.**

**Response `200 OK`:**

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

```bash
curl -s http://localhost:8080/health
```

---

### POST /v1/feedback

Submit user feedback for a completed trace. **Auth required in production.**

```json
{"trace_id": "abc123", "rating": 5, "comment": "helpful"}
```

---

### GET /v1/traces/{trace_id}

Retrieve a redacted trace record. **Auth required in production.**

---

### GET /v1/models

List available Metis models. Returns OpenAI-compatible model objects.

**Response `200 OK`:**

```json
{
  "object": "list",
  "data": [
    {"id": "metis", "object": "model", "created": 1720000000, "owned_by": "metis"},
    {"id": "metis-fast", "object": "model", "created": 1720000000, "owned_by": "metis"},
    {"id": "metis-thinking", "object": "model", "created": 1720000000, "owned_by": "metis"},
    {"id": "metis-council", "object": "model", "created": 1720000000, "owned_by": "metis"},
    {"id": "metis-agent", "object": "model", "created": 1720000000, "owned_by": "metis"}
  ]
}
```

```bash
curl -s http://localhost:8080/v1/models \
  -H "Authorization: Bearer $METIS_API_KEY"
```

---

### POST /v1/chat/completions

Run a query through the Metis cognitive stack. Supports synchronous JSON responses and Server-Sent Events (SSE) streaming.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | no | `metis` | Model name — see [Models](#models) |
| `messages` | array | **yes** | — | Chat messages (`role`, `content`) |
| `stream` | boolean | no | `false` | Enable SSE streaming |
| `temperature` | float | no | — | Accepted but not forwarded to brain |
| `max_tokens` | int | no | — | Accepted but not forwarded to brain |

**Message roles:** `system`, `user`, `assistant`, `tool`

Messages are flattened into a single query string by `OpenAIMetisBridge.messages_to_query()`:

```
[system]
You are a helpful assistant.

[user]
Explain async/await in Python
```

---

## Models

| Model | Route | Description |
|-------|-------|-------------|
| `metis` | Auto (classifier) | Default — router selects `fast`, `thinking`, `council`, or `agent` |
| `metis-fast` | `fast` | Single LLM completion — factual, low-ambiguity queries |
| `metis-thinking` | `thinking` | Extended chain-of-thought reasoning |
| `metis-council` | `council` | Understanding Council + layered MoA + verifier |
| `metis-agent` | `agent` | Plan → Act → Observe → Reflect loop with tools/MCP |

**Legacy aliases** (one release): `superbrain`, `superbrain-fast`, `superbrain-thinking`, `superbrain-council`, `superbrain-agent`

Mapping is defined in `metis/api/bridge.py`:

```python
MODEL_ROUTE_MAP = {
    "metis-fast": RouteMode.FAST,
    "metis-thinking": RouteMode.THINKING,
    "metis-council": RouteMode.COUNCIL,
    "metis-agent": RouteMode.AGENT,
}
```

Per-module `modules:` configuration in YAML affects **internal brain quality** — the API surface is unchanged.

---

## Request Schema

```json
{
  "model": "metis-council",
  "messages": [
    {"role": "system", "content": "You are a concise technical writer."},
    {"role": "user", "content": "Explain the CAP theorem in three paragraphs."}
  ],
  "stream": false
}
```

**Limits:**

- `messages` must be non-empty — `400` if missing
- Request body size capped by `METIS_MAX_REQUEST_BYTES` (default `1048576` bytes) or `security.max_request_body_bytes` in config — `413` if exceeded

---

## Response Schema

**Non-streaming `200 OK`:**

```json
{
  "id": "chatcmpl-a1b2c3d4e5f6...",
  "object": "chat.completion",
  "created": 1720000000,
  "model": "metis-council",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The CAP theorem states that..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 240,
    "total_tokens": 360
  }
}
```

**Usage tokens** are estimated from internal LLM call count (`llm_calls × 10/20/30`), not actual provider token counts.

**Run status** (internal, via bridge metadata): `success`, `needs_clarification`, or `error`. Clarification responses appear as assistant `content` with questions from the confidence gate.

---

## Streaming (SSE)

Set `"stream": true` to receive Server-Sent Events.

**Response headers:**

```http
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**Event format:**

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1720000000,"model":"metis-council","choices":[{"index":0,"delta":{"content":"The CAP"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1720000000,"model":"metis-council","choices":[{"index":0,"delta":{"content":" theorem"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1720000000,"model":"metis-council","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Metis runs the full cognitive pipeline first, then streams the completed answer in ~8-character chunks via `bridge.stream_tokens()`.

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-fast",
    "stream": true,
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }'
```

---

## Error Responses

| Status | Condition | Detail |
|--------|-----------|--------|
| `400` | Empty `messages` | `messages is required` |
| `401` | Missing/invalid auth | `Missing or invalid Authorization header. Use: Bearer sk-...` |
| `401` | Wrong key | `Invalid API key` |
| `413` | Body too large | `Request body too large` |
| `500` | Production without key | `METIS_API_KEY must be set in production mode` |
| `503` | Brain not initialized | `Metis not initialized` |

---

## Examples

### Start the server

```bash
pip install -e ".[distributed]"

export METIS_API_KEY=sk-your-secret-key
export METIS_PRODUCTION=true
export METIS_CONFIG_PATH=config.production.yaml

metis-serve --host 0.0.0.0 --port 8080
```

### Auto-route (classifier picks path)

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis",
    "messages": [{"role": "user", "content": "Summarize the Byzantine Generals Problem"}]
  }'
```

### Council path (full reasoning stack)

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-council",
    "messages": [{"role": "user", "content": "Design a fault-tolerant message queue"}]
  }'
```

### Agent path (tools + MCP)

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-agent",
    "messages": [{"role": "user", "content": "Search for recent papers on mixture-of-agents"}]
  }'
```

### Thinking path

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-thinking",
    "messages": [{"role": "user", "content": "Prove sqrt(2) is irrational"}]
  }'
```

### Fast path

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-fast",
    "messages": [{"role": "user", "content": "Capital of France?"}]
  }'
```

### VS Code Continue

```json
{
  "models": [{
    "title": "Metis Council",
    "provider": "openai",
    "model": "metis-council",
    "apiBase": "http://localhost:8080/v1",
    "apiKey": "sk-your-secret-key"
  }]
}
```

### Cursor

1. **Settings → Models**
2. Enable **Override OpenAI Base URL** → `http://localhost:8080/v1`
3. Set API key to your `METIS_API_KEY`

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — cognitive stack and routing
- [DEPLOYMENT.md](DEPLOYMENT.md) — Docker and production setup
- [SECURITY.md](SECURITY.md) — threat model and mitigations
- [DISTRIBUTED.md](DISTRIBUTED.md) — multi-node cluster
