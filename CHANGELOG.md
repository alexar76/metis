# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-09

### Added

- **Observability** — structured JSON logging, `trace_id` per request, per-module spans, redacted prompts by default (`METIS_LOG_CONTENT=redacted`), tamper-evident audit log
- **CLI observability** — `metis logs trace|tail|stats`
- **Reliability** — failure classification, exponential backoff retries, per-endpoint circuit breakers (YAML config)
- **Knowledge layer** — `KnowledgeStore` (SQLite + TF-IDF, pgvector-ready), `ExperienceReplay`, `FailurePatterns`
- **Council knowledge context** — reads similar verified past TaskSpecs before synthesizing
- **Feedback API** — `POST /v1/feedback {trace_id, rating, comment}` (auth required in production)
- **Trace API** — `GET /v1/traces/{trace_id}` (redacted, auth required in production)
- **Detailed health** — `GET /health` includes nodes, circuit breaker status, knowledge entry count
- **CLI knowledge** — `metis knowledge export` → JSONL for offline SFT
- **Production config** — `config.example.yaml` updated with observability, knowledge, hybrid pro+flash+LM Studio modules
- **Documentation** — `OBSERVABILITY.md`, `KNOWLEDGE.md` (EN/RU/ES), wiki pages, architecture knowledge-flow diagram
- **Integration tests** — observability, knowledge, API feedback/traces, CLI logs

### Changed

- API version bumped to 0.2.0
- `create_provider` wraps LLM calls with resilient retry + circuit breaker when configured
- `Metis.run()` persists traces and auto-saves verified experiences

## [0.1.0] - 2026-07-09

### Added

- **Metis exoskeleton** — multi-agent reasoning orchestrator over any LLM (`Metis` / `CognitiveExoskeleton`)
- **Understanding Council** — 6 parallel isolated agents → structured `TaskSpec`
- **Confidence gate** — fail-closed routing before expensive solve paths
- **Layered Mixture-of-Agents (MoA)** — diverse proposers → refiner → aggregator with diversity enforcement
- **DGPD (Disagreement-Gated Pipeline Depth)** — L0–L3 adaptive depth with agreement scoring and security overrides
- **Agent loop** — plan-act-observe-reflect with built-in tools and MCP integration
- **Verifier** — LLM judge with retry loop against TaskSpec contract
- **Memory** — working, episodic, and TF-IDF vector long-term store
- **Agentic RAG** — query decomposition and iterative retrieval
- **Smart router** — heuristic + LLM classification (fast/thinking/council/agent)
- **Extended thinking** — chain-of-thought with optional self-consistency voting
- **Built-in tools** — sandboxed code interpreter, SSRF-protected web search
- **MCP client** — stdio and SSE transports with alexar76 ecosystem presets
- **Economy layer** — usage metering, cost estimation, session budget gates, webhook export
- **Distributed cluster** — coordinator + worker nodes with HMAC signing and failover
- **OpenAI-compatible API** — `/v1/chat/completions`, `/v1/models`, streaming SSE
- **Security** — prompt injection detection, canary tokens, SSRF protection, rate limiting, audit logging
- **Module registry** — per-role model assignment with base-model fallback
- **Docker** — multi-service compose (coordinator, nodes, production profile)
- **CLI** — `metis`, `metis-serve`, `metis-node`, `metis-coordinator`, `metis-cluster`
- **Documentation** — EN/RU/ES architecture, API, deployment, security guides
- **Landing page** — `docs/landing/index.html` with GitHub Pages instructions
- **Wiki** — GitHub wiki-compatible pages (EN + RU/ES key pages)
- **CI/CD** — GitHub Actions for pytest on push and wheel release on tag
- **Backward compatibility** — `SUPERBRAIN_*` / `COGNITIVE_*` env vars and `superbrain-*` model aliases

### Changed

- Renamed package from `superbrain` to `metis`

[0.2.0]: https://github.com/alexar76/metis/releases/tag/v0.2.0
[0.1.0]: https://github.com/alexar76/metis/releases/tag/v0.1.0
