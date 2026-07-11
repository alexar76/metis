# Metis — comparative benchmark (2026-07-11)

Real HTTP calls against the deployed node (`metis.modelmarket.dev`, reasoning on
DeepSeek, vision on OpenRouter `nemotron-nano-12b-v2-vl:free`) and the raw provider
APIs directly. **No mocks, no synthetic data.** Small samples — directional, not a
leaderboard. Raw data: [`benchmark-2026-07-11.json`](benchmark-2026-07-11.json).
Charted report (Artifact): https://claude.ai/code/artifact/f937a885-f5db-49f1-a168-464081f93838

## 1. Latency by route (median of 3 queries)

| Route | Median latency | Per-query (s) | What runs |
|-------|---------------:|---------------|-----------|
| `fast` | **2.8 s** | 1.8 / 3.0 / 3.5 | single call (L0) |
| `thinking` | **7.4 s** | 1.8 / 10.0 / 10.5 | extended chain-of-thought (L1) |
| `council` | **47.9 s** | 18.3 / 62.5 / 62.9 | council → gate → MoA → verifier (L3, ~12 calls) |

Deeper routes buy deliberation + a verify score, and cost seconds. The demo
auto-routes and only escalates to council when a query needs it.

## 2. A single LLM call vs. the Metis stack (5 checkable traps)

| Metric | Direct DeepSeek | Metis (council) |
|--------|----------------:|----------------:|
| Accuracy | 5 / 5 | 5 / 5 |
| Confidence signal | none | **0.92 avg** (verify_score) |
| Median latency | 0.3 s | 27.8 s |
| Deliberation | 1 call | ~12 calls |

On easy factual questions a strong model is already right — Metis ties on accuracy.
Its differentiator is a **machine-readable confidence score** (per-question:
1.0 / 1.0 / 1.0 / 1.0 / 0.60) a bare call never emits, so an autonomous caller can
gate / retry / ask. Spend the council budget on hard, ambiguous, high-stakes steps.

## 3. Vision — raw endpoint vs. through Metis (same window)

| Path | Success | Note |
|------|--------:|------|
| raw OpenRouter (single-shot ×5) | **0 / 5** | free tier throttled in this window |
| through Metis (bounded retries ×3) | **2 / 3** | retries recover; honest fail-over otherwise |

Same flaky free backend; Metis's bounded-retry + honest fail-over makes it usably
reliable. A small OpenRouter credit removes the throttling.

## 4. Multilingual (answer in the interface language)

| Language | Latency | Answered in language |
|----------|--------:|:--------------------:|
| English | 1.7 s | ✓ |
| Русский | 1.6 s | ✓ |
| Español | 1.3 s | ✓ |

Same question, answer returned in the requested language regardless of the
question's language — what the landing's EN/RU/ES switcher drives.

## Honest caveats
- **Council is expensive** (~18–63 s, ~12 calls) — deep mode, not the default.
- **The verifier is strict** — open-ended answers sometimes score low; that's a
  conservative signal, the answer text is still returned.
- **Free vision throttles** — reliability swings with the free tier's limits.
- **Easy questions favour the raw call** — Metis's edge is hard/ambiguous/high-stakes
  steps + the confidence signal, not trivia speed.

## Reproduce
Harness: `scripts/bench.py` on the node (reads keys from `deploy/prod.yaml`), or adapt
to hit any `metis-serve`. Routes via `POST /v1/verify`; raw providers hit directly.
