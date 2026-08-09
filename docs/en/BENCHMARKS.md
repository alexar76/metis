# Benchmarks — Direct API vs Metis

Compare **single direct LLM calls** against the full **Metis exoskeleton** (understanding council, confidence gate, MoA, verifier) on the same models and prompts.

> [!IMPORTANT]
> **Metis is a risk / confidence gate — not a faster trivia engine.**
> On checkable tasks a strong raw model often ties Metis on accuracy and wins on latency.
> Use Metis when you need a machine-readable `verify_score`, trap catching, or a fail-closed
> gate before an autonomous step compounds. Details below → [Where Metis wins](#where-metis-wins--read-this-first).

Canonical engine: **`deepseek-v4-pro`** (not the legacy `deepseek-chat` alias).
Diversifiers on OpenRouter: **MiniMax-M3**, **Kimi-K3**.

Live evidence:

| Report | What it proves |
|--------|----------------|
| [`HEAD-TO-HEAD-2026-07-11.md`](../benchmarks/HEAD-TO-HEAD-2026-07-11.md) | Metis council vs raw frontier — **where Metis wins** |
| [`HEAD-TO-HEAD-2026-08-08.md`](../benchmarks/HEAD-TO-HEAD-2026-08-08.md) | Fresh raw bake-off: V4-Pro · MiniMax-M3 · Kimi-K3 |
| [`BENCHMARK-2026-07-11.md`](../benchmarks/BENCHMARK-2026-07-11.md) | Latency by route + confidence signal |

---

## Where Metis wins — read this first

> Source: [HEAD-TO-HEAD-2026-07-11 § When to use Metis](../benchmarks/HEAD-TO-HEAD-2026-07-11.md#when-to-use-metis--and-when-not) · raw JSON [`bench-headtohead-2026-07-11.json`](../benchmarks/bench-headtohead-2026-07-11.json)

### Measured accuracy win (same base model)

24 checkable items (math / logic / science / deduction / **6 traps**). Real HTTP, no mocks.

| System | Overall | Traps (6) | Median latency |
|--------|:-------:|:---------:|---------------:|
| DeepSeek-V4-Pro **(raw)** | **96%** | 5/6 | ~0.3 s |
| Kimi K2.6 / Qwen3-Max / GLM-5.2 **(raw)** | 96% | 5/6 | ~1–1.5 s |
| MiniMax-M3 **(raw)** | 100% | **6/6** | ~6.6 s |
| **Metis (V4-Pro council)** | **100%** | **6/6** | ~90 s |

**Metis advantage here:** same engine (V4-Pro) went **96% → 100%** by catching the
System-1 trap *“how many months have exactly 28 days?”* (answer **12**) that four raw
frontier models missed. MiniMax raw also aced traps alone — so Metis is not “smarter than
every model”; it **lifts its own base** and emits a confidence signal no raw call has.

### All-star diversity win (hard olympiad set)

| Config | Score | Note |
|--------|:-----:|------|
| Best single strong model | **90%** | — |
| **Metis all-star council** (DeepSeek + Kimi + Qwen-Max + GLM + MiniMax) | **100%** | Solved the one item **no solo model** cracked |

→ [`bench-extravariants-2026-07-11.json`](../benchmarks/bench-extravariants-2026-07-11.json) · Exp D in the July write-up.

### What raw models never emit

| Signal | Raw LLM | Metis |
|--------|:-------:|:-----:|
| Answer text | ✓ | ✓ |
| Machine-readable **`verify_score` / `verified`** | ✗ | ✓ |
| Fail-closed **`needs_clarification`** | ✗ | ✓ |

That gate is why the factory calls Metis on high-stakes stages — see [`docs/metis-integration.md`](../../../docs/metis-integration.md).

### When Metis does **not** win (honest)

| Situation | Result |
|-----------|--------|
| Already-strong model on checkable / easy tasks | Same accuracy, **~15× slower** — use the model raw |
| Weak models in council (esp. weak aggregator) | Can score **below** the best weak model alone (60% vs 90%) |

**One line:** Metis = **verifier + lift for a mid-tier engine — not a garbage amplifier.**

---

## Frontier bake-off 2026-08-08 (actual run)

> Live HTTP on 2026-08-08. Calibration set (8 items). **Raw calls only** (no council in this refresh).
> Full write-up: [`HEAD-TO-HEAD-2026-08-08.md`](../benchmarks/HEAD-TO-HEAD-2026-08-08.md) · JSON [`bench-frontier-2026-08-08.json`](../benchmarks/bench-frontier-2026-08-08.json)

| System | Acc | trap | math | logic | Median latency |
|--------|:---:|:---:|:---:|:---:|---------------:|
| **MiniMax-M3** | **87.5%** (7/8) | **3/3** | 3/4 | 1/1 | 4.9 s |
| DeepSeek-V4-Pro | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 5.0 s |
| Kimi-K3 | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 11.8 s |
| DeepSeek-V4-Flash | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 2.5 s |
| Kimi-K2.6 | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 15.2 s |

**Complementary blind spots (why prod mixes them):**

| Item | V4-Pro | MiniMax-M3 | Kimi-K3 |
|------|:---:|:---:|:---:|
| Months with exactly 28 days? (**12**) | ✗ | **✓** | ✗ |
| Coin-change for $1 (**242**) | **✓** | ✗ | **✓** |

Prod architecture (already live): **V4-Pro** in high-leverage seats + **MiniMax-M3** as skeptic / `intent_parser_b` + **V4-Flash** on cheap seats. Optional: Kimi-K3 as a third diversifier for open-ended work.

Re-run:

```bash
export DEEPSEEK_API_KEY=...
export OPENROUTER_API_KEY=...
python3 metis/scripts/bench_frontier_bakeoff.py
```

---

## Quick start (harness)

```bash
cd metis
pip install -e ".[dev]"

# Offline (CI-safe, mock provider)
metis-benchmark run --mock --dataset simple --compare direct,metis

# DeepSeek live (canonical engine)
export DEEPSEEK_API_KEY=sk-...
metis-benchmark run --models deepseek-v4-pro --dataset all --compare direct,metis \
  --output reports/bench-$(date +%Y%m%d).md

# Frontier diversifiers via OpenRouter
export OPENROUTER_API_KEY=sk-or-...
metis-benchmark run --models deepseek-v4-pro,minimax-m3,kimi-k3 --dataset reasoning --compare direct

metis-benchmark list-models
metis-benchmark list-datasets
```

## What we measure

| Metric | Description |
|--------|-------------|
| **Latency (ms)** | Wall-clock per case |
| **Tokens in/out** | From provider usage or estimates |
| **Estimated cost (USD)** | Via Metis economy `CostCalculator` |
| **Calls count** | Direct = 1; Metis = metered LLM events |
| **Depth level** | Route estimate (fast=1 … council=12) |
| **Pass rate** | Per-case checkers (see datasets) |

## Datasets

| File | Category | Cases | Intent |
|------|----------|------:|--------|
| `task_understanding.jsonl` | trap, ambiguous | 12 | Metis should clarify before acting |
| `reasoning.jsonl` | reasoning | 12 | Verifiable math/logic answers |
| `factual.jsonl` | factual | 10 | Static world knowledge |
| `simple.jsonl` | simple | 10 | Trivial — Direct should be faster |

## Environment variables

| Variable | Provider |
|----------|----------|
| `DEEPSEEK_API_KEY` | `deepseek-v4-pro`, `deepseek-v4-flash` @ `api.deepseek.com` |
| `OPENROUTER_API_KEY` | `minimax-m3`, `kimi-k3`, `kimi-k2.6` @ `openrouter.ai` |
| `OPENAI_API_KEY` | `gpt-4o-mini` @ `api.openai.com` |
| _(none)_ | `qwen3:8b` via local Ollama |

## CI

- `pytest -m benchmark` — mock harness tests (no keys).
- `.github/workflows/benchmark.yml` — **manual dispatch only**; runs live benchmarks when secrets are configured.
