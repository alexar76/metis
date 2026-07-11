# Distributed Cognitive Runtime

This document describes the multi-server architecture that lets individual models run on different machines while the exoskeleton orchestrates them as a single secured "metis".

## Topology

```
                    ┌─────────────────────┐
                    │   Coordinator       │
                    │ (metis CLI /    │
                    │  CognitiveExoskel.) │
                    └──────────┬──────────┘
                               │ secure RPC
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
    │  node-eu-1  │     │  node-us-1  │     │ node-asia-1 │
    │ qwen3:8b    │     │ phi4-mini   │     │ mistral:7b  │
    │ intent/     │     │ red_team/   │     │ synthesizer │
    │ proposer    │     │ refiner     │     │ aggregator  │
    └─────────────┘     └─────────────┘     └─────────────┘
```

- **Worker nodes** host one or more model endpoints (`metis-node serve`).
- **Coordinator** runs the Understanding Council, MoA, verifier, and routing — it never calls models directly when `distributed: true`; it uses `RemoteLLMProvider` over HTTP RPC.
- **Mesh**: any node can be added/removed; the `NodeRegistry` handles discovery, health checks, and failover.

## Node abstraction

Each node is described by a `NodeDescriptor`:

| Field | Purpose |
|-------|---------|
| `id` | Unique node identifier |
| `url` | Base URL (`https://eu1.example.com:8443`) |
| `models` | Models hosted on this node |
| `roles` | Council/MoA roles this node can serve |
| `api_key_env` | Env var name for bearer token (never plaintext in YAML) |

## Inter-node protocol

Worker nodes expose:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/metis/health` | GET | Liveness + model/role list |
| `/metis/invoke` | POST | RPC: run completion on local model |
| `/v1/chat/completions` | POST | Optional OpenAI-compatible proxy |

Request/response schemas are defined in `metis/distributed/protocol.py` (Pydantic).

### Invoke request

```json
{
  "model": "qwen3:8b",
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "temperature": 0.7,
  "max_tokens": 4096,
  "request_id": "uuid",
  "caller_node": "coordinator"
}
```

## Security

| Layer | Implementation |
|-------|----------------|
| Transport | TLS (`tls_verify` in cluster config) |
| Authentication | Bearer token per node via `METIS_NODE_*_KEY` env vars |
| Request signing | Optional HMAC-SHA256 (`timestamp + body`) with `METIS_HMAC_SECRET` |
| Secrets | Never stored in config files — env vars only |
| Audit | Structured JSON logs of cross-node calls (no prompt content by default) |

Headers when signing is enabled:

```
Authorization: Bearer <token>
X-Cognitive-Timestamp: <unix_seconds>
X-Cognitive-Signature: <hmac_sha256_hex>
```

## Configuration

### Cluster config (`cluster_config.yaml`)

```yaml
coordinator:
  url: https://coord.example.com

nodes:
  - id: node-eu-1
    url: https://eu1.example.com:8443
    api_key_env: METIS_NODE_EU1_KEY
    models: [qwen3:8b]
    roles: [intent_parser, proposer]

security:
  tls_verify: true
  request_signing: true
  hmac_secret_env: METIS_HMAC_SECRET
```

### Runtime config integration

```yaml
distributed: true
cluster_config: cluster_config.yaml

council_models:
  - {name: parser_a, model: qwen3:8b, node_id: node-eu-1}
  - {name: parser_b, model: phi4-mini, node_id: node-us-1}
  - {name: red_team, model: qwen3:8b, node_id: node-us-1}
  - {name: synthesizer, model: mistral:7b, node_id: node-asia-1}
```

When `distributed: true`, `create_provider()` resolves `ModelSlot.node_id` → `NodeRegistry` → `RemoteLLMProvider`.

## Failover

1. `NodeRegistry.check_health()` probes `/metis/health` on all nodes.
2. `RemoteLLMProvider` tries the primary node, then `failover_candidates()` with matching role/model.
3. Failed nodes are marked `unhealthy` until the next health check passes.

## CLI

```bash
# Install distributed extras (FastAPI node server)
pip install -e ".[dev,distributed]"

# Start worker nodes (one per terminal)
export METIS_NODE_LOCAL_KEY=dev-key-1
metis-node serve --config node_config.yaml --production --port 8443

export METIS_NODE_LOCAL_KEY=dev-key-2
metis-node serve --config node_config.yaml --production --port 8444 --node-id node-2

# Check cluster health
metis-cluster status --config cluster_config.yaml

# Run query through distributed cluster
metis "Your question" --cluster cluster_config.yaml --production
```

## Local demo with 2 mock nodes

See README "Distributed mode" section for a step-by-step local demo using two mock worker nodes on `127.0.0.1:8443` and `127.0.0.1:8444`.

## Module map

| File | Responsibility |
|------|----------------|
| `node.py` | `NodeDescriptor`, health state |
| `registry.py` | Discovery, health checks, failover |
| `remote_provider.py` | `LLMProvider` over HTTP RPC |
| `coordinator.py` | Parallel dispatch across nodes |
| `security.py` | Auth, HMAC, audit logging |
| `protocol.py` | Pydantic request/response schemas |
| `server.py` | FastAPI worker node server |
| `cli.py` | `metis-node`, `metis-cluster` commands |

## Design principles

1. **No direct model coupling** — agents talk to nodes via RPC, not shared GPU memory.
2. **Same exoskeleton API** — `Metis` works unchanged; distribution is a config flag.
3. **Heterogeneous nodes recommended** — different models per node can increase effective diversity (Yang et al., 2026[^scaling]); not a guarantee when aggregation is synthesis-only (Li et al., 2025[^selfmoa]).
4. **Fail closed on auth** — missing/invalid tokens reject requests; no anonymous fallback.

## Heterogeneity and research

| Practice | Research basis | Confidence |
|----------|----------------|------------|
| Different `models` per node | Complementary channels beat homogeneous scaling at lower N[^scaling] | **Likely** on reasoning benchmarks |
| Same model on all nodes | Diminishing returns beyond small N[^scaling] | **Proven** on 7B–8B vote/debate benchmarks |
| Role spread across regions | Engineering convenience; not independently validated | **Plausible** |

[^scaling]: Yang et al., *Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity*, arXiv:2602.03794, 2026.
[^selfmoa]: Li et al., *Rethinking Mixture-of-Agents*, arXiv:2502.00674, 2025 — single strong model may beat heterogeneous mix for synthesis.

See [RESEARCH.md](en/RESEARCH.md) for full digest.
