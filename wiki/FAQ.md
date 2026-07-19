# FAQ

## General

### What is Metis?

Metis (μῆτις) is a distributed cognitive layer over any LLM. It orchestrates multi-agent reasoning — councils, layered MoA, agent loops, verification, and economy metering — behind a single OpenAI-compatible API.

### Does Metis include a chat UI?

No. Metis is API-only. Use VS Code Continue, Cursor, `curl`, or the `metis` CLI.

### What LLM providers are supported?

Any OpenAI-compatible endpoint (Ollama, vLLM, LiteLLM, OpenAI, DeepSeek) plus native Anthropic. See [Configuration](Configuration).

### How is Metis different from calling an LLM directly?

A single LLM makes one interpretation. Metis runs parallel council agents, gates pipeline depth with DGPD, synthesizes via layered MoA, verifies with a judge, and meters cost — improving quality on ambiguous or high-stakes tasks at higher latency/cost.

## API

### What is the primary API endpoint?

`POST /v1/chat/completions` — OpenAI-compatible chat completions.

### What models can I request?

| Model | Behavior |
|-------|----------|
| `metis` | Auto-route (classifier picks depth) |
| `metis-fast` | Single-pass, low latency |
| `metis-thinking` | Extended reasoning |
| `metis-council` | Full council + MoA |
| `metis-agent` | Tool-using agent loop |

### Is authentication required?

Optional in development. Required in production (`--production` or `METIS_PRODUCTION=true`).

### What about streaming?

Check current API support in [docs/en/API.md](https://github.com/alexar76/metis/blob/main/docs/en/API.md).

## Configuration

### What is DGPD?

**Disagreement-Gated Pipeline Depth** — skips expensive MoA layers when council agents agree above a threshold. High-risk keywords force full depth.

### How do I use different models per council role?

Use the `modules:` section in `config.yaml`. See [Configuration](Configuration).

### What are legacy env var names?

`SUPERBRAIN_*` and `COGNITIVE_*` are accepted as aliases for one release cycle. Prefer `METIS_*`.

## Distributed

### How do I run a cluster?

Use `metis-node` for workers, `metis-coordinator` for the coordinator, or `docker compose up` for a containerized stack. See [Docker Deployment](Docker-Deployment).

### How is inter-node traffic secured?

TLS, Bearer auth (`METIS_NODE_*_KEY`), HMAC signing (`METIS_HMAC_SECRET`), rate limiting, and body size limits.

## Economy

### How does billing work?

Metis meters tokens per model, applies cost tables, enforces session budgets, and can export usage via webhook to AIMarket Hub. See [Ecosystem](Ecosystem).

### How do I reduce cost?

- Use `--route fast` or `metis-fast` for simple queries
- Reserve `metis-council` for ambiguous/high-stakes tasks
- Run local Ollama models (zero API cost)
- Enable DGPD to skip MoA on agreement
- Set `session_budget_usd`

## Ecosystem

### How does Metis fit in alexar76?

Metis is the reasoning layer. Argus is the demand-side client. AIMarket Hub handles pay-per-call metering. Oracle gateway provides MCP tools.

### Can I use MCP tools without AIMarket?

Yes. Configure custom `mcp_servers` in `config.yaml` with any MCP-compatible server.

## Development

### How do I run tests?

```bash
pip install -e ".[dev,distributed]"
pytest -v
```

### Is cognitive-runtime the same project?

No. `cognitive-runtime` was an early fork. **Metis** is canonical.

## Related

- [Quick Start](Quick-Start)
- [Troubleshooting](Troubleshooting)
- [Architecture](Architecture)
