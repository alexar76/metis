# Metis — maturity & honest limitations

Metis is one of the **strongest** ecosystem components (external reviews ~8/10). This doc states
what is production-grade today vs what still needs soak testing and adversarial benchmarks.

**Related:** Factory [KI-8](../../docs/known-issues.md#ki-8--metis-distributed-mode--adversarial-verification-gap) · [DISTRIBUTED.md](./DISTRIBUTED.md) · [benchmarks/](../benchmarks/)

---

## What is solid

| Area | Status |
|------|--------|
| Confidence gate (fail-closed) | Implemented — `metis/gates/`; blocks low composite / unresolved ambiguities |
| Verifier-with-retry | Independent verify path; machine-readable `verify_score` / `verified` |
| Mixture-of-agents + council | Documented architecture; integration tests |
| OpenAI-compatible API | Hub capability + Factory bridge |
| Security defaults | Auth, rate limits, body size — see [SECURITY.md](./SECURITY.md) |

---

## Known gaps (critique validated)

### Distributed mode — **beta**

Multi-node coordinator (TLS + Bearer + HMAC) is **implemented** but not **soak-proven**:

- No published 48h multi-region failure injection report
- Partition / stale registry / clock skew behavior undocumented in production
- **Label:** use single-node for reliability; cluster for experiments only until KI-8 closes

### Confidence gate — trusts council scores

The gate combines `TaskSpec.confidence` with structural bonuses/penalties. It does **not**
independently re-estimate truthfulness. A council that assigns **0.95 confidence** to a subtly
wrong interpretation can **PROCEED** if ambiguities omit `needs_user_input: true`.

Regression tests: `metis/tests/test_adversarial_gates.py` document this class.

**Mitigation:** route high-stakes Factory stages through `/v1/verify` and **hard-fail** on
`verified: false`; do not rely on confidence alone.

### Verifier — limited adversarial corpus

Benchmarks cover trap/ambiguous cases ([`benchmarks/report.py`](../benchmarks/report.py)) but
there is **no wide red-team suite** (encoding, contradictory sources, confident fabrication).

**Mitigation:** expand `metis/benchmarks/` adversarial track (KI-8).

### Economy metering — consumer-enforced

Token/cost metering exists for observability and billing hooks; **hard enforcement** depends on
the caller (Factory debit, Hub channel) — Metis alone will not block a runaway loop if the
consumer ignores budgets.

---

## Recommended use today

| Use case | OK? |
|----------|-----|
| Factory architect/methodologist **confidence signal** | ✅ with verify hard-fail |
| Public API on trusted network with auth | ✅ |
| Multi-region HA inference mesh | ⚠️ beta only |
| Sole guard against subtle hallucination | ❌ — pair with verify + human gates |

---

## Path to “production hardened”

1. KI-8 soak + adversarial benchmark publication
2. Distributed mode **beta** label removed after soak green
3. Document high-stakes preset: `enforce_confidence_gate: true` + mandatory verify

**Russian:** see ecosystem [maturity review RU](../../docs/ecosystem-maturity-review.ru.md)
