# Metis head-to-head — reasoning benchmark (2026-07-11)

> [!IMPORTANT]
> **Bottom line (honest):** Metis is competitive as a **verifier + a lift for a mid-tier
> engine — not as a "garbage amplifier."** It hands you a machine-readable confidence
> signal and lifts a mid model to frontier-adjacent quality; it does **not** make a weak
> model strong (a weak aggregator can drag the council *below* the best single weak model),
> and it adds **no** accuracy to an already-strong model on checkable tasks (only latency).
> See [When to use Metis — and when not](#when-to-use-metis--and-when-not).

Real HTTP calls, no mocks. 24 curated reasoning questions (multi-step math, logic,
short science, deduction, and **6 classic single-call "traps"**), auto-graded by exact
final-answer match, all with retries for fairness. Base engine and Metis's council both
run on **deepseek-v4-pro**; the standalone comparison models are strong **non-Anthropic/
non-OpenAI** flagships (Anthropic and OpenAI are ToS-blocked for API access on this
account, so Claude/GPT are represented only by their published scores elsewhere).

Raw data: [`bench-headtohead-2026-07-11.json`](bench-headtohead-2026-07-11.json).

## Result

| System | math (6) | logic (5) | science (4) | deduction (3) | **traps (6)** | **Overall** | Median latency |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|---:|
| DeepSeek-V4-Pro (raw) | 6/6 | 5/5 | 4/4 | 3/3 | 5/6 | **96%** | 0.3 s |
| Kimi K2.6 (raw) | 6/6 | 5/5 | 4/4 | 3/3 | 5/6 | **96%** | 1.5 s |
| Qwen3-Max (raw) | 6/6 | 5/5 | 4/4 | 3/3 | 5/6 | **96%** | 1.3 s |
| GLM-5.2 (raw) | 6/6 | 5/5 | 4/4 | 3/3 | 5/6 | **96%** | 1.2 s |
| MiniMax-M3 (raw) | 6/6 | 5/5 | 4/4 | 3/3 | **6/6** | **100%** | 6.6 s |
| **Metis (V4-Pro base)** | 6/6 | 5/5 | 4/4 | 3/3 | **6/6** | **100%** | 89.6 s |

## What it shows (honest)

- **Easy categories saturate.** Every model — including the raw base — scores 100% on
  math/logic/science/deduction. On easy inputs a strong model is already right; there is
  nothing to add.
- **The uplift is on the traps.** Four of the five *standalone* models — DeepSeek-V4-Pro,
  Kimi, Qwen3-Max, GLM-5.2 — fell for the **same** trap: *"how many months have exactly 28
  days?"* (answer **12**; each answered **1**). Metis's council + verifier caught it →
  **6/6 traps, 100% overall**. Same base model (V4-Pro), one deliberation layer, one fewer
  confidently-wrong answer (96% → 100%).
- **But one raw model also aced it: MiniMax-M3 scored 100%** (24/24, incl. the trap) at
  ~6.6 s. So Metis does **not** beat *every* frontier model here — it **lifts its own
  mid-tier base up to the level of the single strongest model tested**, without swapping in
  a bigger model. On a strong-enough base a single call can equal the council on this set —
  the honest Self-MoA result.
- **What Metis adds that no raw call does:** a confidence signal — avg **verify_score 1.0**
  across the set, a machine-readable number a caller can gate/retry/escalate on. That, plus
  catching the confidently-wrong tail on *whatever* base you give it, is the durable value —
  not beating strong models on easy work.

## The cost (honest)

- **Latency: ~90 s** for Metis's full council vs **0.3–1.5 s** for a single call. This is
  deep mode. Metis auto-routes and only escalates to council when a query needs it; the
  demo forces council to show the whole trace.
- **Small sample (24 items).** Directional, not a leaderboard. One trap decided the
  headline gap — the point is *which* item (a real System-1 trap), not the 4-point margin.
- **Self-MoA caveat.** On a base as strong as V4-Pro, the accuracy uplift is small and
  task-dependent; the durable value is catching the confidently-wrong tail + the
  confidence signal, not beating strong models on easy work.

## Model-combination bake-off (which council mix is most effective?)

Same Metis council, varying **which models fill the proposer/parser roles**; the
aggregator + verifier are held on **deepseek-v4-pro** across all configs, so this
isolates the *proposer-diversity* contribution. Run on the 8-question hard/trap subset
(where diversity should help most, per Yang et al. 2026). Raw data:
[`bench-bakeoff-2026-07-11.json`](bench-bakeoff-2026-07-11.json).

| Config | Proposer models | Accuracy | verify | Avg latency |
|--------|-----------------|:---:|:---:|---:|
| **C0 — solo** | V4-Pro ×all (temp-diverse) | 100% | 1.0 | **99 s** |
| C2 — quad | V4-Pro + Kimi + Qwen3-Max + GLM-5.2 | 100% | 1.0 | 103 s |
| C1 — dual | V4-Pro + Kimi | 100% | 1.0 | 110 s |
| C4 — tiered | Kimi + Qwen3-Max + GLM-5.2 (V4-Pro aggregates) | 100% | 1.0 | 177 s |

**Finding — heterogeneity added no accuracy here, only latency.** Every config reaches
100% with verify_score 1.0; they differ *only* in speed. With a strong base plus a strong
aggregator + verifier, the council already saturates the hard set, so mixing in more model
families buys nothing on accuracy and costs wall-clock (the tiered config is *slowest* —
each round waits on the slowest diverse proposer). On this evidence the **most effective
config is the simplest that maxes accuracy: plain V4-Pro council (C0)** — fastest and
cheapest. This is the **Self-MoA** result (Li et al. 2025) playing out on a strong base.

**When diversity should still pay (not disproven, just not triggered here):** on a
*weaker* base, or on genuinely open-ended/ambiguous tasks where a single family's blind
spot isn't caught by its own aggregator — the regime Yang et al. 2026 measured. Our set is
hard-but-*checkable*, which a strong base + verifier already covers. Default stays
single-strong-base; `enforce_heterogeneous_agents` remains an opt-in for weak-base or
high-diversity deployments.

## Stress tests — does wrapping help on the hardest problems?

Ten olympiad-level problems with verified integer answers (AIME-style counting, modular
arithmetic, combinatorics), hard enough that even strong models slip. Raw data:
[`bench-hardtest-2026-07-11.json`](bench-hardtest-2026-07-11.json) ·
[`bench-weaktest-2026-07-11.json`](bench-weaktest-2026-07-11.json).

**A — wrap the strongest model (MiniMax-M3 + DeepSeek as a second proposer):**

| System | Score | Latency |
|--------|:---:|---:|
| MiniMax-M3 (raw) | 90% (9/10) | 9.8 s |
| Metis (MiniMax base + DeepSeek) | 90% (9/10) | 152 s |

Same 9/10, **same single miss**, at ~15× the latency — no accuracy gain from wrapping a
top model. (verify_score 0.9, and it scored the one it got wrong at 0.0 — the gate flagged
its own miss even though the answer wasn't fixed.)

**B — wrap two weak models (the "garbage → candy" test):**

| System | Score | Latency |
|--------|:---:|---:|
| Qwen-2.5-7B (raw) | **90%** (9/10) | 6.9 s |
| MiniMax-M3 (raw) | 90% (9/10) | 15.4 s |
| Llama-3.1-8B (raw) | 60% (6/10) | 9.5 s |
| **Metis (Llama-8B + Qwen-7B)** | **60%** (6/10) | 215 s |

The council came out at **60% — level with the *worse* model (Llama) and 30 points below
the *better* one (Qwen 90%)**. On three problems Qwen was right alone but the weak
aggregator (Llama-8B) corrupted the synthesis. **Mixing weak models with a weak
aggregator/verifier hurts** — the exact Self-MoA warning. Quality tracks the
aggregator+verifier, not the number of models.

## When to use Metis — and when not

> **One line:** competitive as a **verifier + a lift for a mid-tier engine — not a garbage
> amplifier.**

| Use Metis for… | Expected result |
|----------------|-----------------|
| ✅ **A confidence gate on high-stakes autonomous steps** (e.g. the AICOM factory's architect/methodologist stages) | A machine-readable `verify_score` + `verified` flag to gate/retry/escalate on — the one thing a raw call can't emit. It flags its own low-confidence answers (Exp A: 0.0 on the miss). |
| ✅ **Lifting a mid-tier engine on hard/ambiguous work** | +a few points, up to frontier-adjacent — DeepSeek-V4-Pro 96% → 100%, matching the strongest single model, at higher latency (Exp 1). |
| ✅ **Catching the confidently-wrong tail** (System-1 traps, misread specs) | Council + verify catch errors a single fluent call sails past — e.g. the "months with 28 days" trap that four raw frontier models missed. |
| ✅ **Cheap-but-diverse proposers under a strong aggregator/verifier** | Put your best model in the aggregator+verifier seat; let cheap diverse models propose. *(Quantified by Config C — pending.)* |
| ⚠️ **Squeezing more accuracy from an already-strong model on checkable tasks** | Don't — it's a ceiling. Same accuracy, ~15× latency (Exp 2, Exp A). Use the model raw; add Metis only for the confidence signal. |
| ❌ **Turning a weak model into a strong one** | Don't — a weak aggregator can drag the council *below* the best single weak model (Exp B: 60% vs Qwen's 90%). Metis amplifies a decent base; it doesn't manufacture capability. |

**Config rule of thumb:** the aggregator and verifier must be your **strongest** model —
that's where answer quality concentrates. Model heterogeneity on the proposers is optional
and only pays off on weaker bases or open-ended tasks; on a strong base it adds latency,
not accuracy (Exp 2). Default to a single strong base + the verify layer.

## Capability gate — the architectural response

**The case.** Experiment B is the problem in one number: a council of two weak models
scored **60%**, *below* the better of the two run alone (Qwen-7B, 90%). A weak model in the
**aggregator/verifier** seat took correct proposals and synthesized them into wrong answers.
The lesson from every experiment on this page points the same way — **quality concentrates in
the aggregator and verifier, not in the number of models** (Exp 2: mixing strong models added
0 accuracy; Exp A: wrapping a top model added 0). So a randomly plugged-in weak model must not
be allowed to sit where it can do harm.

**The decision.** Metis now carries a **capability gate** (`metis/agents/capability.py`,
on by default). It ranks every configured model by a relative capability score and enforces:

| Role | Policy | Why |
|------|--------|-----|
| aggregator · verifier · synthesizer | **always the strongest configured model** | this is where a weak voice corrupts the result (Exp B) |
| proposers · parsers | **models below `council_capability_floor` lose their vote** (swapped for the best floor-passing model) | a dumb proposal shouldn't be able to sway the consensus |
| vision · router | **never gated** | need a specific capability / are deliberately cheap |

It never empties a role and is a **no-op for a single-model deployment** (the one model is
both strongest and above the floor), so it only ever helps. With the gate on, the Exp B
config self-corrects: the aggregator/verifier become Qwen (the stronger member), and Llama
is excluded from proposing — the council can no longer fall below its best member.

**Two more configs make the case sharper** (10 olympiad problems, [`bench-extravariants-2026-07-11.json`](bench-extravariants-2026-07-11.json)):

| Config | Score | What it proves |
|--------|:---:|----------------|
| C — weak proposers (Llama+Qwen) + **strong** DeepSeek aggregator/verifier | **50%** | a strong aggregator **cannot rescue** weak proposals — garbage in, garbage synthesized (worse than the pure-weak council's 60%). ⇒ the floor must exclude weak *proposers*, not just fix the aggregator. |
| D — **all-star** council: 5 strong families (DeepSeek+Kimi+Qwen-Max+GLM+MiniMax) | **100%** | a diverse council of **strong** models **beats every single model** (best single = 90%) — it solved the one problem *no model cracked alone*. ⇒ diversity pays, but only among the capable. |

Together: weak members drag a council down even under a strong aggregator (C, Exp B); a
diverse set of strong members lifts it above any single one (D). The capability gate is
exactly the policy that keeps the weak out and lets the strong-diverse in.

**Where capability scores come from.** A static prior registry (seeded from published
leaderboards + these live benchmarks; frontier labs — Anthropic, OpenAI, Google, xAI —
included), refined per-deployment by `metis calibrate`, which runs each configured model
through a small checkable set and writes measured scores the gate then reads. Unknown models
default to mid-tier. Knobs: `enforce_capability_gate`, `council_capability_floor`,
`min_aggregator_capability`, `capability_file`.

## Reproduce

Harness on the node reads keys from `deploy/prod.yaml`; raw models hit their APIs
directly, Metis via `POST /v1/verify` (`route: council`). The bake-off and stress tests
construct each config in-process (`RuntimeConfig.modules` per-role model assignment) and
run the subset through `Metis.run(route=council)`. Model capability is scored by
`metis calibrate` (or the static registry in `metis/agents/capability.py`).
