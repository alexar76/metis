# Configuration

Metis is configured via `config.yaml` and `METIS_*` environment variables.

## Minimal config

```yaml
provider: ollama
base_model: "qwen3:8b"
base_url: "http://localhost:11434/v1"
api_key: "ollama"
default_route: council
```

Copy `config.example.yaml` as a starting point.

## Key settings

| Setting | Default | Description |
|---------|---------|-------------|
| `default_route` | `council` | Default pipeline: `fast`, `thinking`, `agent`, `council` |
| `confidence_threshold` | `0.7` | Minimum confidence to proceed without clarification |
| `enforce_confidence_gate` | `true` | Fail-closed gate before expensive solve paths |
| `max_agent_iterations` | `5` | Agent loop iteration limit |
| `max_verify_retries` | `3` | Verifier retry limit |
| `enable_web_search` | `true` | Web search in agent loop |
| `enable_code_interpreter` | `true` | Sandboxed code execution |
| `enable_long_term_memory` | `true` | Episodic + vector memory |

## Per-module models

Preferred over legacy `council_models` list. Each role can use a different provider:

```yaml
modules:
  intent_parser_a:
    provider: openai_compat
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
    temperature: 0.5
  intent_parser_b:
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
  red_team:
    model: qwen3:8b
    base_url: http://localhost:11434/v1
  synthesizer:
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
  judge:
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
```

Validate:

```bash
metis config validate -c config.yaml
metis config show-modules -c config.yaml
```

## DGPD

```yaml
dgpd:
  enabled: true
  agreement_threshold: 0.85
  force_full_depth_keywords:
    - delete
    - execute
    - password
    - production
    - deploy
```

## Council diversity

```yaml
enforce_heterogeneous_agents: false
min_unique_council_models: 2
```

Set `enforce_heterogeneous_agents: true` to hard-reject councils where all parsers share the same model + endpoint.

## Economy

```yaml
economy:
  enabled: true
  currency: USD
  session_budget_usd: 5.0
  aimarket_hub_url: https://modelmarket.dev
  webhook_url: https://your-billing-endpoint/usage
  models:
    gpt-4o: {input_per_1m: 2.50, output_per_1m: 10.00}
    deepseek-chat: {input_per_1m: 0.14, output_per_1m: 0.28}
    qwen3:8b: {input_per_1m: 0, output_per_1m: 0}
```

## MCP tools

```yaml
enable_mcp_tools: true
mcp_ecosystem_presets:
  - aimarket-oracle-gateway
mcp_servers:
  - name: aimarket-oracle-gateway
    transport: stdio
    command: python
    args: ["-m", "aimarket_oracle_gateway.mcp_stdio_server"]
    env:
      AIMARKET_HUB_URL: https://modelmarket.dev
    tool_prefix: oracle
```

## Environment variables

All config uses the `METIS_` prefix:

| Variable | Purpose |
|----------|---------|
| `METIS_API_KEY` | API authentication key |
| `METIS_PRODUCTION` | Enable production mode |
| `METIS_NODE_A_KEY` | Worker node Bearer token |
| `METIS_HMAC_SECRET` | Request signing secret |
| `METIS_RATE_LIMIT_PER_MINUTE` | Rate limit override (default 60) |

Legacy aliases `SUPERBRAIN_*` and `COGNITIVE_*` are accepted for one release cycle.

## Production config

Use `config.production.yaml` with `--production` flag:

```bash
export METIS_API_KEY=your-key
metis "query" -c config.production.yaml --production
metis-serve -c config.production.yaml --production
```

Never enable `allow_test_provider` or mock provider in production.

## Distributed cluster

```yaml
# cluster_config.yaml
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

## Related

- [Architecture](Architecture) — module roles and provider matrix
- [Docker Deployment](Docker-Deployment) — container env files
- [Ecosystem](Ecosystem) — AIMarket economy config
