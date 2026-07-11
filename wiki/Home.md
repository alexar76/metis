# Metis Wiki

**Metis** (μῆτις) — a distributed cognitive layer over any LLM. Multi-agent reasoning orchestrator in the [alexar76](https://github.com/alexar76) AIMarket ecosystem.

## What Metis does

A single LLM makes one interpretation of your task. Metis wraps any model with:

- **Understanding Council** — parallel diverse agents → structured `TaskSpec`
- **DGPD** — Disagreement-Gated Pipeline Depth (skip expensive layers on agreement)
- **Layered MoA** — propose → refine → aggregate
- **Agent loop** — plan, act, observe, reflect with tools + MCP
- **Verifier** — judge checks answer against task contract
- **Economy** — usage metering, cost attribution, budget gates
- **OpenAI-compatible API** — `POST /v1/chat/completions` for IDE integration

## Quick links

| Page | Description |
|------|-------------|
| [Architecture](Architecture) | System design and per-module model config |
| [Quick Start](Quick-Start) | Install, CLI, first query |
| [Configuration](Configuration) | `config.yaml`, env vars, modules |
| [Docker Deployment](Docker-Deployment) | `docker compose` stack |
| [IDE Integration](IDE-Integration) | Continue, Cursor, model routing |
| [Ecosystem](Ecosystem) | alexar76 / AIMarket integration |
| [Research Evidence](Research-Evidence) | Citations behind design choices |
| [FAQ](FAQ) | Common questions |
| [Troubleshooting](Troubleshooting) | Errors and fixes |

## CLI commands

| Command | Purpose |
|---------|---------|
| `metis` | Run a query through the cognitive stack |
| `metis-serve` | OpenAI-compatible API (`/v1/chat/completions`) |
| `metis-node` | Start a distributed worker node |
| `metis-coordinator` | Start the cluster coordinator |
| `metis-cluster` | Check cluster node health |

## Documentation (repo)

Full guides with diagrams live in the repository:

- [docs/en/README.md](https://github.com/alexar76/metis/blob/main/docs/en/README.md) — user guide
- [docs/en/ARCHITECTURE.md](https://github.com/alexar76/metis/blob/main/docs/en/ARCHITECTURE.md) — architecture deep dive
- [docs/en/API.md](https://github.com/alexar76/metis/blob/main/docs/en/API.md) — API reference

## Languages

- **English** (this wiki)
- [Русский](https://github.com/alexar76/metis/tree/main/wiki/ru)
- [Español](https://github.com/alexar76/metis/tree/main/wiki/es)

## License

MIT
