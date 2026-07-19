# IDE Integration

Metis is **API-only** — no bundled chat UI. Connect your IDE via the OpenAI-compatible API at `/v1/chat/completions`.

## Start the server

```bash
pip install -e ".[distributed]"
export METIS_API_KEY=sk-your-secret   # optional in dev
metis-serve -c config.yaml --port 8080
```

Production:

```bash
export METIS_API_KEY=sk-your-secret
metis-serve -c config.production.yaml --production --port 8080
```

Docker:

```bash
docker compose up -d --build
# API at http://localhost:8080
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service health |
| `/v1/models` | GET | List available models |
| `/v1/chat/completions` | POST | Run query through Metis brain |

## Model routing

OpenAI-compatible model IDs control pipeline depth:

| Model | Route | Use case |
|-------|-------|----------|
| `metis` | Auto (classifier) | Default — router picks depth |
| `metis-fast` | Fast | Low latency, single pass |
| `metis-thinking` | Extended thinking | Deeper reasoning |
| `metis-council` | Council | Full Understanding Council + MoA |
| `metis-agent` | Agent | Tool-using agent loop |

The bare name `metis` lets the internal classifier choose the route. Suffix models **force** a pipeline depth.

Legacy `superbrain-*` model names are accepted for one release.

## VS Code Continue

Add to `.continue/config.json`:

```json
{
  "models": [
    {
      "title": "Metis Council",
      "provider": "openai",
      "model": "metis-council",
      "apiBase": "http://localhost:8080/v1",
      "apiKey": "sk-your-secret"
    },
    {
      "title": "Metis Fast",
      "provider": "openai",
      "model": "metis-fast",
      "apiBase": "http://localhost:8080/v1",
      "apiKey": "sk-your-secret"
    }
  ]
}
```

## Cursor

In Cursor settings, add a custom OpenAI-compatible model:

- **Base URL:** `http://localhost:8080/v1`
- **API Key:** your `METIS_API_KEY`
- **Model:** `metis-council` (or `metis-fast` for quick completions)

## curl example

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-council",
    "messages": [
      {"role": "user", "content": "Refactor this function to use async/await"}
    ]
  }'
```

## Authentication

| Mode | Behavior |
|------|----------|
| Development | Auth optional if `METIS_API_KEY` unset |
| Production (`--production`) | `METIS_API_KEY` required; 401 without valid Bearer token |

## Rate limiting

Default: 60 requests/minute per API key or IP. Override with `METIS_RATE_LIMIT_PER_MINUTE`.

## Per-module config and API quality

The `modules:` section in `config.yaml` affects **internal brain quality** — the API surface is unchanged. Configure different models per council role for best results.

```bash
metis config show-modules -c config.yaml
```

## Tips

- Use `metis-fast` for autocomplete-style quick completions
- Use `metis-council` for ambiguous or high-stakes architectural decisions
- Use `metis-agent` when you need web search or tool execution
- Set `session_budget_usd` in economy config to cap spend per session

## Related

- [Quick Start](Quick-Start)
- [Configuration](Configuration)
- [Architecture](Architecture)
