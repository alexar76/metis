# Metis — test & benchmark results

_Last run: 2026-07-10._

## Test suites — all green (220 tests)

| Suite | Command | Result |
|-------|---------|--------|
| **Metis core** | `pytest --cov=metis` (in `metis/`) | **199 passed** (incl. live-trace SSE) |
| **Factory confidence-gate** | `pytest tests/test_metis_gate*.py` (repo root) | **13 passed** |
| **Alien-monitor node + chat** | `pytest tests/test_metis_graph.py` (in `alien-monitor/`) | **8 passed** |

Latest cycle added the **live cognition trace** (`tests/test_pipeline_event_sink.py`, 9 tests): the
ambient `ContextVar` event-sink (set/clear, reaches `asyncio.gather` children, pure no-op by default,
swallows sink exceptions) and the `POST /v1/verify/stream` SSE endpoint (ordered real-event frames +
`done` envelope for council; sparse no-verify trace for fast; validation errors before streaming; no
sink leak across requests; a plain `run()` is byte-identical). Verified live on
**https://metis.modelmarket.dev** with the real DeepSeek model (council streamed the full pipeline →
`verify_score` in the `done` envelope).

Earlier test coverage this cycle:

- **Ecosystem provider surface** — `POST /v1/verify` + `POST /aimarket/invoke` (verification
  envelope), input coercion, validation, fail-safe error handling, standalone-with-no-ecosystem,
  and per-IP **rate-limit (429)**.
- **Grounded verifier** — code that fails execution forces the verdict to fail regardless of
  the LLM judge; clean code corroborates; no-code/disabled falls back safely.
- **Multimodal** — image SSRF/injection validation (block localhost/`169.254.169.254`,
  `data:image/*` only, ≤5 cap), extraction from OpenAI messages, vision→council path, graceful
  `multimodal_unsupported`, `/v1/chat/completions` with images.
- **Factory gate** — auto-detect + fail-open (proceeds unchanged when Metis is unreachable),
  verdict mapping, `metis_gate` product-extra SQLite round-trip.
- **Paid ecosystem-invoke tool** — `AIMarketInvokeTool` pays hub capabilities
  (`POST /ai-market/v2/invoke` + payment channel); tested against a **real local HTTP hub**
  (no mocks): success + channel forwarding, 402 payment-required, SSRF block, unreachable
  fail-safe, and registration only when `enable_ecosystem_invoke` + a hub URL are set.
- **Security hardening** — constant-time API-key compare, server-side timeout, exception-type-only
  logging, internal cluster URLs stripped from the monitor, plus a **token-bucket
  negative-elapsed bug fix** (first request was wrongly rejected at `burst=1`).

## Benchmarks

Harness: [`benchmarks/`](../benchmarks/) — compares **Direct** (one LLM call) vs **Metis**
(council → verify) over **47 cases**: factual / reasoning / code / ambiguous / trap / simple.

### Run real numbers (requires a live LLM)

```bash
ollama pull qwen3:8b
metis-benchmark run --models qwen3:8b --route council -o reports/bench.md
```

### Real run — DeepSeek, `simple` dataset, Direct vs Metis (council)

_2026-07-10 · no mocks · [`reports/bench-real-deepseek.md`](../reports/bench-real-deepseek.md)_

| Runner | Cases | Pass rate | Avg latency | Avg cost | Avg LLM calls |
|--------|------:|----------:|------------:|---------:|--------------:|
| direct | 10 | **80%** | 1.0 s | $0.00003 | 1.0 |
| **Metis** (council) | 10 | **90%** | 11.1 s | $0.0021 | 12.1 |

**Reading it honestly:** Metis lifts pass rate (**80% → 90%**) by deliberating + verifying, at
~11× latency and ~12× calls/cost. That is the whole thesis — spend the multi-agent budget on
**hard / high-stakes** steps, not on easy FAQs (where Direct wins on speed). Bigger datasets:
`metis-benchmark run --models deepseek-chat --dataset all --route council -o reports/bench.md`.

> The harness also has an offline `--mock` smoke mode for CI (validates plumbing only — mock
> returns placeholder text, so those numbers are **not** a quality measure).
