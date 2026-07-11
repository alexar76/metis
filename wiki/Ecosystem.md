# Ecosystem

Metis is the **reasoning and orchestration layer** in the [alexar76](https://github.com/alexar76) AIMarket agent economy — above raw LLM endpoints, below demand-side agents like Argus.

## Ecosystem map

| Project | Role |
|---------|------|
| **Metis** | Multi-agent reasoning, councils, verification, economy metering |
| **Argus** | Demand-side production agent with WARDEN MCP filters |
| **Dioscuri** | Paired services |
| **AIMarket Hub** | Pay-per-call marketplace and metering |
| **aimarket-oracle-gateway** | 35 verifiable oracle tools via MCP |
| **aimarket-plugins** | 15 hub plugins via MCP |
| **Helios** | Observability |
| **aicom** | Product manufacturing factory pipeline |
| **acex** | Capital market pricing |
| **pulse-terminal** | Trading terminal |

## MCP tool integration

Metis connects to AIMarket MCP servers in the agent loop:

```yaml
enable_mcp_tools: true
mcp_ecosystem_presets:
  - aimarket-oracle-gateway
  - aimarket-plugins
```

| Server | Tools | Config preset |
|--------|-------|---------------|
| aimarket-oracle-gateway | 35 verifiable oracle tools | `aimarket-oracle-gateway` |
| aimarket-plugins | 15 hub plugins | `aimarket-plugins` |

Tool outputs are wrapped as untrusted data before entering the LLM context.

## Economy integration

Metis's economy layer aligns with AIMarket pay-per-call metering:

```yaml
economy:
  enabled: true
  currency: USD
  session_budget_usd: 5.0
  aimarket_hub_url: https://modelmarket.dev
  webhook_url: https://your-billing-endpoint/usage
```

Usage events flow: Metis → Usage Meter → Cost Calculator → Webhook → AIMarket Hub.

## When to use what

| Scenario | Use |
|----------|-----|
| Ambiguous task needing TaskSpec | **Metis** council route |
| Simple factual Q&A | Metis `--route fast` or direct API |
| Production agent with payments | **Argus** + aimarket-agent |
| Verifiable randomness/oracles | Metis agent + oracle-gateway MCP |
| Product manufacturing | **aicom** factory pipeline |

## Architecture wins (honest)

| Change | Reliability |
|--------|-------------|
| Confidence gate | **Likely** — early stop, not correctness guarantee |
| Verifier + retry | **Likely** — judge is still an LLM |
| Heterogeneous MoA (≥2 models) | **Likely** with real model diversity |
| MCP tool transport | **Guaranteed** for tool access |
| Injection sanitization | **Likely** — reduces attack surface |
| Session budget gate | **Guaranteed** for spend caps |

## Links

- [Research Evidence](Research-Evidence) — citations behind design choices
- [Ecosystem knowledge base](https://github.com/alexar76/aicom/blob/main/docs/ecosystem/knowledge-base.md)
- [aimarket-protocol](https://github.com/alexar76/aimarket-protocol)
- [aimarket-oracle-gateway](https://github.com/alexar76/aimarket-oracle-gateway)
- Full guide: [docs/en/ECOSYSTEM.md](https://github.com/alexar76/metis/blob/main/docs/en/ECOSYSTEM.md)
