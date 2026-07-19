# Architecture

Metis is **API-only** — no bundled chat UI. Integrate via `metis` CLI, Python API, or OpenAI-compatible HTTP endpoints.

> Full architecture guide: [docs/en/ARCHITECTURE.md](https://github.com/alexar76/metis/blob/main/docs/en/ARCHITECTURE.md)

## Layers

| Layer | Responsibility |
|-------|----------------|
| **Input Sanitizer** | Injection detection, canary tokens, role enforcement |
| **Router** | Classifies complexity → route mode (fast, thinking, agent, council) |
| **Confidence Gate** | Fail-closed before solve; returns clarification questions when confidence is low |
| **Understanding Council** | Parallel agents → structured `TaskSpec` |
| **DGPD** | Disagreement-Gated Pipeline Depth — skip MoA layers when agents agree |
| **Layered MoA** | Proposers → refiner → aggregator |
| **Agent Loop** | Plan-Act-Observe-Reflect with tools, web search, MCP |
| **Verifier** | Judge validates answer vs TaskSpec; retry on failure |
| **Economy** | Token metering, cost tables, session budget gates |
| **Memory** | Working + episodic + vector store (RAG) |

## Data flow

1. User query → sanitize input
2. Router classifies task → route mode
3. Economy budget check
4. Council produces `TaskSpec`
5. Confidence gate evaluates (clarify or proceed)
6. DGPD gates MoA depth based on inter-agent agreement
7. MoA and/or agent loop generates answer
8. Verifier checks; retry with feedback if failed
9. Economy usage report

## Per-module model configuration

Each brain module (council role, MoA proposer, judge, router) can target a **different LLM endpoint**. Unconfigured roles fall back to `base_model` / `base_url`.

```yaml
modules:
  intent_parser_a:
    provider: openai_compat
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
  synthesizer:
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
```

Validate and inspect:

```bash
metis config validate -c config.yaml
metis config show-modules -c config.yaml
```

## Provider matrix

| Provider | `provider` value | Typical `base_url` |
|----------|------------------|-------------------|
| Ollama (local) | `ollama` | `http://localhost:11434/v1` |
| OpenAI | `openai_compat` | `https://api.openai.com/v1` |
| DeepSeek | `openai_compat` | `https://api.deepseek.com/v1` |
| Anthropic | `anthropic` | (native API) |
| Distributed node | `openai_compat` | node URL + `node_id` |
| vLLM / LiteLLM | `openai_compat` | your proxy URL |

## Module roles

| Role | Pipeline stage |
|------|----------------|
| `intent_parser_a/b/c` | Understanding Council — parallel interpretation |
| `constraint_extractor` | Council — constraints |
| `ambiguity_hunter` | Council — ambiguities |
| `red_team` | Council — adversarial reading |
| `synthesizer` | Council — TaskSpec merge |
| `moa_proposer_logician/pragmatist/skeptic` | MoA layer 1 |
| `moa_refiner` | MoA layer 2 |
| `moa_aggregator` | MoA layer 3 |
| `judge` | Verifier |
| `router` | Query classifier |

## DGPD

**Disagreement-Gated Pipeline Depth** skips expensive MoA layers when council agents agree above a threshold. High-risk keywords (`delete`, `production`, `deploy`, etc.) force full depth regardless.

```yaml
dgpd:
  enabled: true
  agreement_threshold: 0.85
```

## Distributed architecture

See [Docker Deployment](Docker-Deployment) and [docs/en/DISTRIBUTED.md](https://github.com/alexar76/metis/blob/main/docs/en/DISTRIBUTED.md).

Coordinator dispatches to worker nodes with TLS, Bearer auth, HMAC signing (`X-Metis-Timestamp`, `X-Metis-Signature`), and automatic failover.

## Security

Production mode enforces: API key auth, rate limiting, HMAC request signing, injection scanning, SSRF protection on web search, and audit logs that exclude prompt content.

## Related

- [Configuration](Configuration)
- [IDE Integration](IDE-Integration)
- [Research Evidence](Research-Evidence)
