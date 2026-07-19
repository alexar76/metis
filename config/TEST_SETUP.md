# Hybrid Test Setup — DeepSeek v4-pro + v4-flash + LM Studio

Local smoke-test configuration mixing **DeepSeek v4-pro** (deep reasoning), **DeepSeek v4-flash** (fast/cheap), and **phi-4 reasoning** (LM Studio local).

> **Security:** API keys live only in `.env` (gitignored). Never commit keys to YAML, code, or docs.
>
> **Rotate your DeepSeek key** if it was shared in chat, logs, or screenshots. Generate a new key at [platform.deepseek.com](https://platform.deepseek.com/) and update `.env`.

## Prerequisites

- Metis installed (`pip install -e .` in repo root)
- [LM Studio](https://lmstudio.ai/) with local server on port `1234`
- DeepSeek API account with billing enabled

## Environment variables

Create `.env` in the repo root (already in `.gitignore`):

```bash
DEEPSEEK_API_KEY=sk-...          # from DeepSeek platform — never commit
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_API_KEY=lm-studio       # LM Studio accepts any string
```

Load before running:

```bash
set -a && source .env && set +a
```

For `metis-benchmark` with ad-hoc model ids (not in the built-in catalog), also set:

```bash
export METIS_BASE_URL=https://api.deepseek.com/v1
```

## Discovered model IDs (2026-07-09)

| Provider | Endpoint | Model IDs |
|----------|----------|-----------|
| **DeepSeek API** | `https://api.deepseek.com/v1` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| **LM Studio** | `http://localhost:1234/v1` | Server up; **no model loaded for inference** |

Query models yourself:

```bash
curl https://api.deepseek.com/v1/models \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY"

curl http://localhost:1234/v1/models
```

### LM Studio — load phi-4 or qwen

1. Open LM Studio → load **phi-4 reasoning** (8GB variant) or a **qwen** checkpoint.
2. Start the local server (default port `1234`).
3. Re-run `curl http://localhost:1234/v1/models` and note the exact `id`.
4. Update `model:` in `intent_parser_b` (currently placeholder `phi-4-reasoning-plus`).

At setup time, `/v1/models` listed `qwen/qwen3.6-35b-a3b` and others, but chat returned *"No models loaded"* — weights must be loaded in the LM Studio UI before local modules work.

## Model diversity matrix

`config/test-hybrid.yaml` assigns models by cognitive role:

| Tier | Model | Roles | Rationale |
|------|-------|-------|-----------|
| **Flash** (fast) | `deepseek-v4-flash` | `intent_parser_a`, `constraint_extractor`, `ambiguity_hunter`, `judge`, `router`, `moa_proposer_pragmatist`, `moa_proposer_skeptic`, `moa_aggregator` | Lower latency, ~3× cheaper than pro |
| **Pro** (deep) | `deepseek-v4-pro` | `intent_parser_c`, `red_team`, `synthesizer`, `moa_proposer_logician`, `moa_refiner` | Harder reasoning, adversarial critique, synthesis |
| **Local** (offline) | `phi-4-reasoning-plus` | `intent_parser_b` | Endpoint diversity vs cloud parsers |

All three intent parsers use **different model+endpoint pairs** — `check_parser_diversity_warning` passes with no shared signatures.

## Economy pricing (cache-miss, USD per 1M tokens)

Official [DeepSeek API pricing](https://api-docs.deepseek.com/quick_start/pricing) (2026-07):

| Model | Input | Output | vs pro |
|-------|------:|-------:|--------|
| `deepseek-v4-flash` | $0.14 | $0.28 | baseline |
| `deepseek-v4-pro` | $0.435 | $0.87 | ~3.1× input, ~3.1× output |
| `phi-4-reasoning-plus` | $0 | $0 | local |

Configured in `config/test-hybrid.yaml` under `economy.models` for `CostCalculator` metering.

## Config file

`config/test-hybrid.yaml` — per-module routing (summary):

| Role | Model | Endpoint |
|------|-------|----------|
| `intent_parser_a` | `deepseek-v4-flash` | DeepSeek API |
| `intent_parser_b` | phi-4 / qwen (local) | LM Studio |
| `intent_parser_c` | `deepseek-v4-pro` | DeepSeek API |
| `constraint_extractor`, `ambiguity_hunter` | `deepseek-v4-flash` | DeepSeek API |
| `red_team`, `synthesizer`, `moa_proposer_logician`, `moa_refiner` | `deepseek-v4-pro` | DeepSeek API |
| `judge`, `router`, MoA flash roles | `deepseek-v4-flash` | DeepSeek API |

All cloud modules use `api_key_env: DEEPSEEK_API_KEY`; local modules use `api_key_env: LMSTUDIO_API_KEY`.

Validate (loads `.env` automatically via pydantic-settings):

```bash
metis config validate -c config/test-hybrid.yaml
metis config show-modules -c config/test-hybrid.yaml
```

## Smoke test

### 1. DeepSeek v4-pro — direct API

```bash
curl https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"What is 2+2?"}],"max_tokens":50}'
```

### 2. DeepSeek v4-flash — direct API

```bash
curl https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"What is 2+2?"}],"max_tokens":50}'
```

### 3. LM Studio — **BLOCKED** until model loaded

Chat to `phi-4-reasoning-plus` returns `400` / *"No models loaded"*. Load phi-4 or qwen in LM Studio first.

### 4. Metis full pipeline — **BLOCKED** until LM Studio ready

```bash
metis --route council -c config/test-hybrid.yaml "What is 2+2? Explain briefly."
```

Fails at `intent_parser_b` when LM Studio has no model loaded. Cloud-only workaround: point `intent_parser_b` to `deepseek-v4-flash` temporarily.

### 5. Benchmark comparison (flash vs pro vs hybrid)

`metis-benchmark` does not accept `-c`; it benchmarks single model ids. Compare tiers on the `simple` dataset:

```bash
export METIS_BASE_URL=https://api.deepseek.com/v1

# Flash only
metis-benchmark run --models deepseek-v4-flash --dataset simple --compare direct \
  --output reports/bench-flash-simple.md

# Pro only
metis-benchmark run --models deepseek-v4-pro --dataset simple --compare direct \
  --output reports/bench-pro-simple.md
```

Hybrid module routing is exercised via `metis -c config/test-hybrid.yaml` (requires LM Studio for `intent_parser_b`).

## LM Studio status

| Check | Status |
|-------|--------|
| Server reachable (`GET /v1/models`) | **UP** |
| Model loaded for chat | **DOWN** — load phi-4 or qwen in UI |
| Config placeholder | `phi-4-reasoning-plus` (or qwen id from `/v1/models`) |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `env var DEEPSEEK_API_KEY is not set` | `source .env` |
| `400` from `localhost:1234` | Load a model in LM Studio |
| Benchmark skips `deepseek-v4-*` | Set `METIS_BASE_URL=https://api.deepseek.com/v1` |
| Council diversity warning | Should not appear — parsers use flash / local / pro |
