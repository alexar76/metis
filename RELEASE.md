# Metis v0.1.0 Release Notes

**Release date:** 2026-07-09  
**Version:** 0.1.0  
**License:** MIT

## Summary

Metis v0.1.0 is the first public release of the distributed cognitive layer for any LLM. It wraps single-model inference with a production-grade multi-agent stack: Understanding Council, DGPD depth gating, layered MoA, verifier, memory, search, economy metering, distributed cluster support, MCP ecosystem tools, and an OpenAI-compatible HTTP API.

## Highlights

| Feature | Description |
|---------|-------------|
| **Council** | 6 parallel agents produce a structured `TaskSpec` before solving |
| **DGPD** | L0–L3 adaptive pipeline depth saves 60–70% LLM calls on simple queries |
| **MoA** | 3-layer mixture-of-agents with optional refiner skip on agreement |
| **Distributed** | Coordinator dispatches council/MoA roles across worker nodes |
| **OpenAI API** | Drop-in `/v1/chat/completions` for Cursor, Continue, and custom clients |
| **Security** | Injection defense, SSRF blocks, sandboxed code, HMAC cluster auth |
| **Economy** | Per-route metering and session budget gates for AIMarket integration |

## Install

```bash
# PyPI (import + CLI: metis, metis-serve, …)
pip install aimarket-metis
pip install "aimarket-metis[dev,distributed]"

# GitHub tag
pip install "aimarket-metis[distributed] @ git+https://github.com/alexar76/metis.git@v0.2.0"

# From source clone
pip install -e ".[dev,distributed]"
```

## Quick start

```bash
ollama pull qwen3:8b
metis "Explain multi-agent systems" --model qwen3:8b --url http://localhost:11434/v1

# OpenAI-compatible server
metis-serve --port 8080
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"metis-council","messages":[{"role":"user","content":"Hello"}]}'
```

## Docker

```bash
cp config/docker.env.example .env
docker compose up -d --build
```

## Documentation

| Resource | Path |
|----------|------|
| Architecture (EN) | [docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md) |
| API reference | [docs/en/API.md](docs/en/API.md) |
| Deployment | [docs/en/DEPLOYMENT.md](docs/en/DEPLOYMENT.md) |
| Security | [docs/en/SECURITY.md](docs/en/SECURITY.md) |
| Landing page | [docs/landing/index.html](docs/landing/index.html) |
| Wiki | [wiki/Home.md](wiki/Home.md) |

## Ecosystem position

Metis sits in the [alexar76 AI agent economy](https://github.com/alexar76) alongside:

- **cognitive-runtime** — OpenAI API wrapper with DGPD
- **[ARGUS-3](https://github.com/alexar76/argus)** — demand-side reference agent with WARDEN MCP firewall
- **[AIMarket Hub](https://github.com/alexar76/aimarket-hub)** — federated capability catalog and invoke API
- **[aimarket-oracle-gateway](https://github.com/alexar76/aimarket-oracle-gateway)** — verifiable oracle MCP services

## Test coverage

- **119+ tests** passing
- Core modules: exoskeleton, pipeline, council, MoA, API bridge, economy, security

## Breaking changes

None (initial release). Legacy `superbrain-*` model names remain supported for one release cycle.

## Upgrade from superbrain

```bash
# Env vars auto-migrate
export METIS_API_KEY=$SUPERBRAIN_API_KEY

# Model aliases still work
# superbrain-council → metis-council
```

## Git tag

```bash
git tag -a v0.1.0 -m "Metis v0.1.0 — distributed cognitive layer"
```
