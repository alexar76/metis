# Metis frontier bake-off — 2026-08-08

> Real HTTP, no mocks. Calibration set (8 checkable items: traps + multi-step).
> Raw: [`bench-frontier-2026-08-08.json`](bench-frontier-2026-08-08.json).
> Prior evidence: [`HEAD-TO-HEAD-2026-07-11.md`](HEAD-TO-HEAD-2026-07-11.md).
> Summary for docs: [`docs/en/BENCHMARKS.md`](../en/BENCHMARKS.md#where-metis-wins--read-this-first).

> [!IMPORTANT]
> **This file is raw-model diversity only.** Metis’s measured wins (96%→100% on V4-Pro,
> all-star 100% vs 90% solo, `verify_score` gate) live in
> [July HEAD-TO-HEAD → When to use Metis](HEAD-TO-HEAD-2026-07-11.md#when-to-use-metis--and-when-not).
> August reconfirms why MiniMax sits in the skeptic seat (only voice that clears the month-trap).

## Result

| System | Acc | trap | math | logic | Median latency |
|--------|:---:|:---:|:---:|:---:|---:|
| **MiniMax-M3** | **87.5%** (7/8) | **3/3** | 3/4 | 1/1 | 4.9 s |
| DeepSeek-V4-Pro | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 5.0 s |
| Kimi-K3 | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 11.8 s |
| DeepSeek-V4-Flash | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 2.5 s |
| Kimi-K2.6 | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 15.2 s |

## What the misses show (this is the architecture)

| Item | V4-Pro | MiniMax-M3 | Kimi-K3 |
|------|:---:|:---:|:---:|
| Months with exactly 28 days? (**12**) | ✗ (said February-only) | **✓** | ✗ |
| Coin-change for $1 (**242**) | **✓** | ✗ (empty) | **✓** |

**Complementary blind spots.** MiniMax is still the only frontier voice that reliably
catches the classic System-1 month trap (same finding as 2026-07-11). V4-Pro / Kimi-K3
own the hard combinatorics item MiniMax dropped. Putting **both** in the council is not
fashion — it is measured coverage of each other's failure modes.

`deepseek-chat` does not appear anywhere in this bake-off. That name is a **legacy alias**
left in old quickstart snippets; live Metis and this suite use **`deepseek-v4-pro`**.

## Best combination (justified)

| Seat | Model | Why |
|------|-------|-----|
| Base + aggregator + synthesizer + red-team + logician | **`deepseek-v4-pro`** | Highest prior; saturates checkable math; Self-MoA C0 was fastest-to-100% in July |
| Skeptic + intent_parser_b | **`minimax/minimax-m3`** (OpenRouter) | Only model that cleared the trap column twice (Jul + Aug) |
| Optional third diversifier | **`moonshotai/kimi-k3`** | Matches V4-Pro on hard math; use for open-ended / ambiguous, not required for checkable sets |
| Cheap seats (judge, ambiguity, pragmatist, most parsers) | **`deepseek-v4-flash`** | Good enough; saves cost/latency |
| Vision | OpenRouter VL (e.g. Nemotron free) | DeepSeek API is text-only |

**Do not:** put Flash (or any weaker model) in aggregator/verifier — July weaktest showed a
weak aggregator dragging the council *below* its best member (60% vs 90%).

This **is already live** on `metis.modelmarket.dev` (`prod.yaml`: V4-Pro Self-MoA + MiniMax
skeptic). Optional next step: add Kimi-K3 as a third proposer for high-diversity /
ambiguous routes only.

## Re-run

```bash
export DEEPSEEK_API_KEY=...
export OPENROUTER_API_KEY=...
python3 metis/scripts/bench_frontier_bakeoff.py
```
