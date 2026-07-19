# Research digest — heterogeneous multi-agent LLM systems

This document maps **verified** research to metis design choices. Claims are benchmark-specific unless noted; production behavior may differ.

## Summary table

| Paper | Venue / year | What was actually shown | Relevance to metis |
|-------|--------------|-------------------------|-------------------------|
| [Agent Scaling via Diversity](#1-agent-scaling-via-diversity) | arXiv 2026 (OpenReview) | Homogeneous agent scaling saturates; 2 fully diverse agents can match/exceed 16 homogeneous on 7 reasoning benchmarks (7–8B models, vote/debate) | Supports `min_unique_council_models: 2` and distributed heterogeneous nodes |
| [Mixture-of-Agents (MoA)](#2-mixture-of-agents-moa) | ICLR 2025 Spotlight | Layered multi-LLM MoA reaches 65.1% LC win rate on AlpacaEval 2.0 vs GPT-4o 57.5% using open models | Architectural precedent for layered MoA pipeline |
| [Self-MoA](#3-self-moa-counterpoint) | arXiv 2025 | Single strong model + intra-model diversity often beats heterogeneous MoA on AlpacaEval 2.0, MMLU, CRUX, MATH | Heterogeneity is **not** universally optimal for synthesis |
| [When Agents Disagree](#4-when-agents-disagree-selection-bottleneck) | arXiv 2026 | Diversity helps with **judge selection**; MoA-style synthesis can lose to a single model when aggregation is weak | Supports verifier/judge layer; cautions on blind synthesis |
| [MMAD](#5-mmad-sycophantic-drift-in-slm-debate) | OpenReview submission | Naive debate on 3–8B SLMs causes sycophantic drift (accuracy as low as ~10%); MToM framework mitigates | Caution for multi-round debate on small models; council is parallel, not debate |
| [CONSENSAGENT](#6-consensagent) | ACL Findings 2025 | Sycophancy slows MAD consensus and hurts reliability; prompt optimization helps | Supports structured prompts and verifier, not open-ended debate |
| [Peacemaker or Troublemaker](#7-peacemaker-or-troublemaker) | arXiv 2025 | Inter-agent sycophancy collapses debate; can underperform single-agent | Same caution for naive debate loops |

---

## 1. Agent Scaling via Diversity

**Citation:** Yingxuan Yang, Chengrui Qu, Muning Wen, Laixi Shi, Ying Wen, Weinan Zhang, Adam Wierman, Shangding Gu. *Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity.* arXiv:2602.03794, 2026. [PDF](https://arxiv.org/pdf/2602.03794) · [OpenReview](https://openreview.net/forum?id=9BN2W5BCfE) · [Code](https://github.com/SafeRL-Lab/Agent-Scaling)

**What they proved (not overstated):**

- Scaling **homogeneous** agents (same model, prompt, config) shows **strong diminishing returns** on seven benchmarks (GSM8K, ARC, Formal Logic, TruthfulQA, HellaSwag, WinoGrande, Pro Medicine).
- Introducing heterogeneity (different models, personas, prompts, tools — levels L1–L4) yields **complementary evidence**; they formalize this with an information-theoretic bound and a label-free metric **K\*** (effective channels).
- Under **Vote** and **Debate** protocols with 7–8B open models: **L4 (full diversity) with 2 agents matches or exceeds L1 (no diversity) with 16 agents** on reported settings — an 8× agent-count reduction for equivalent or better accuracy.
- Gains are **stronger on multi-step reasoning** (e.g. GSM8K, ARC) than on knowledge-retrieval tasks (e.g. WinoGrande).

**Caveats:**

- Models: Qwen-2.5-7B, Llama-3.1-8B, Mistral-7B (and mixtures). Not tested at GPT-4 scale or in tool-using agents.
- Protocols: vote and debate only — not layered MoA synthesis.
- Benchmark accuracy, not production latency/cost at scale.

**What we adopted:** Require ≥2 distinct models when `enforce_heterogeneous_agents: true`; prefer heterogeneous cluster nodes; avoid scaling identical agents for reasoning tasks.

**What we extrapolated:** That a 5-role Understanding Council with 2–3 models is “enough” — not directly tested; we use role diversity as a **weak** supplement when models differ.

---

## 2. Mixture-of-Agents (MoA)

**Citation:** Junlin Wang, Jue Wang, Ben Athiwaratkun, Ce Zhang, James Zou. *Mixture-of-Agents Enhances Large Language Model Capabilities.* ICLR 2025 (Spotlight). arXiv:2406.04692. [Paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/5434be94e82c54327bb9dcaf7fca52b6-Paper-Conference.pdf) · [arXiv](https://arxiv.org/abs/2406.04692)

**What they proved:**

- **Layered MoA**: proposers in early layers, aggregators in later layers; each agent sees all prior-layer outputs.
- Open-source-only MoA achieves **65.1% length-controlled win rate on AlpacaEval 2.0** vs **57.5% for GPT-4 Omni** (+7.6 pp absolute). Also reports strong results on Arena-Hard, MT-Bench, and FLASK.
- Documents “collaborativeness” — models often improve when shown other models’ outputs.

**Caveats:**

- Benchmarks are **instruction-following / chat quality** (AlpacaEval 2.0, MT-Bench), not multi-step coding agents or long-horizon planning.
- Uses multiple strong open models; does not isolate “diversity” from “include a strong aggregator.”
- Higher cost and latency than single-call inference.

**What we adopted:** Three-layer pattern — parallel proposers → refiner → aggregator (`metis/agents/moa.py`).

**What we extrapolated:** That MoA gains transfer to TaskSpec-driven verification loops — plausible but **not** shown in the original paper.

---

## 3. Self-MoA (counterpoint)

**Citation:** Wenzhe Li, Yong Lin, Mengzhou Xia, Chi Jin. *Rethinking Mixture-of-Agents: Is Mixing Different Large Language Models Beneficial?* arXiv:2502.00674, 2025. [PDF](https://arxiv.org/pdf/2502.00674)

**What they proved:**

- **Self-MoA** (multiple samples from one top model) **outperforms heterogeneous MoA** in many settings: **+6.6 pp** on AlpacaEval 2.0 vs standard MoA; **~+3.8% average** on MMLU, CRUX, MATH.
- MoA is **sensitive to proposer quality**; mixing weaker models can **lower** average quality.
- Heterogeneous mixing can help when models have **complementary task specialization** (e.g. math + code proposers).

**Caveats:**

- Focus on ensemble/synthesis benchmarks, not council-style task interpretation.
- Does not contradict diversity benefits under **voting** (see Agent Scaling paper).

**What we adopted:** Document that heterogeneity is **likely**, not guaranteed; temperature-only diversity on one model is explicitly weak.

**What we extrapolated:** None — this paper is cited as a **limiting** result.

---

## 4. When Agents Disagree (selection bottleneck)

**Citation:** *When Agents Disagree: The Selection Bottleneck in Multi-Agent LLM Pipelines.* arXiv:2603.20324, 2026. [PDF](https://arxiv.org/pdf/2603.20324)

**What they proved (N=210, 42 tasks × 7 categories):**

- **Diverse team + judge-based selection:** 0.810 win rate vs single-model baseline.
- **Homogeneous team + judge:** 0.512 (near chance).
- **MoA-style synthesis** preferred over baseline in **0 of 42 tasks** by their judge panel (Δ WR = +0.631 for judge vs synthesis).
- Closed-form crossover: diversity helps when aggregation/selection quality exceeds a threshold.

**Caveats:**

- Single-round generate-then-select pipelines; not multi-layer iterative MoA.
- Judge quality drives the effect — a weak judge negates diversity gains.

**What we adopted:** Separate **verifier/judge** stage with retry feedback, not pure synthesis-only output.

**What we extrapolated:** That our verifier partially addresses the “selection bottleneck” — **likely** but not validated on our stack.

---

## 5. MMAD (sycophantic drift in SLM debate)

**Citation:** *MMAD: Multi-Agent Mutual Awareness Debate — A Theory-of-Mind Framework for Stabilizing Small Language Model Debate.* OpenReview submission. [OpenReview](https://openreview.net/forum?id=0h3dbL6Iy3) (venue TBD at time of writing)

**What they report:**

- **Naive multi-agent debate** on **small LMs (3–8B)** can **degrade** below single-agent baselines (reported accuracies as low as ~10% on some settings) due to **sycophantic drift** — agents abandon correct answers under peer pressure without superior reasoning.
- **MMAD** (mutual theory-of-mind: peer-level + teacher-level guidance) recovers large gains on GSM8K, CodeQA, CS1QA, CommonsenseQA with Mistral-7B, Phi-4-mini, Qwen2.5-7B.
- Drift rate → 0% by round 4 on GSM8K in their framework.

**Caveats:**

- **Debate** protocol with multiple rounds — metis council agents are **parallel and isolated**, which reduces but does not eliminate conformity risk at synthesis.
- SLM-focused; larger models may behave differently.
- Preprint/submission — not yet a settled venue.

**What we adopted:** Avoid naive multi-round debate on small models; parallel council + structured JSON roles; confidence gate before expensive solve.

**What we extrapolated:** That parallel council avoids MMAD-class drift — **plausible** but not directly tested.

---

## 6. CONSENSAGENT

**Citation:** Priya Pitre, Naren Ramakrishnan, Xuan Wang. *CONSENSAGENT: Towards Efficient and Effective Consensus in Multi-Agent LLM Interactions Through Sycophancy Mitigation.* ACL Findings 2025. [DOI](https://doi.org/10.18653/v1/2025.findings-acl.1141)

**What they proved:**

- Agents in MAD often **agree uncritically** (sycophancy), inflating rounds and cost.
- Trigger-based prompt refinement (**CONSENSAGENT**) improves accuracy and efficiency on six reasoning benchmarks across three models.

**Caveats:**

- Debate-style interaction; different from our MoA layers.

**What we adopted:** Structured system prompts per role; verifier feedback on retry.

---

## 7. Peacemaker or Troublemaker

**Citation:** Binwei Yao, Chao Shang, Wanyu Du, Jianfeng He, Ruixue Lian, Yi Zhang, Hang Su, Sandesh Swamy, Yanjun Qi. *Peacemaker or Troublemaker: How Sycophancy Shapes Multi-Agent Debate.* arXiv:2509.23055, 2025. [PDF](https://arxiv.org/pdf/2509.23055)

**What they proved:**

- Formal sycophancy metrics for multi-agent debate; excessive agreeability causes **disagreement collapse** and can yield **lower accuracy than single-agent** baselines.

**Caveats:**

- Debate frameworks with judges/debaters; model sizes vary by experiment.

**What we adopted:** Red-team role in council; skeptic proposer in MoA; no open-ended peer debate by default.

---

## Architecture mapping

| Metis claim | Research support | Confidence |
|------------------|------------------|------------|
| ≥2 heterogeneous models for council/MoA | Agent Scaling (2 vs 16); MoA uses multiple models | **Likely** on reasoning; weak on single-model+temperature |
| Layered MoA (propose → refine → aggregate) | MoA (ICLR 2025) | **Proven** on chat/instruction benchmarks |
| Parallel council (no cross-talk during interpret) | Mitigates debate sycophancy risk (MMAD, CONSENSAGENT) | **Plausible**, not A/B tested here |
| Verifier + retry | Selection bottleneck paper; CONSENSAGENT | **Likely** if judge is capable |
| More homogeneous agents ≠ linear gains | Agent Scaling diminishing returns | **Proven** on 7 benchmarks, 7–8B models |
| Heterogeneous MoA always beats homogeneous | **Contradicted** by Self-MoA on synthesis benchmarks | Use diversity when models complement; else prefer one strong model |

---

## Bibliography

1. Yang, Y., et al. (2026). Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity. arXiv:2602.03794. https://arxiv.org/abs/2602.03794
2. Wang, J., et al. (2025). Mixture-of-Agents Enhances Large Language Model Capabilities. ICLR 2025. arXiv:2406.04692. https://arxiv.org/abs/2406.04692
3. Li, W., et al. (2025). Rethinking Mixture-of-Agents: Is Mixing Different Large Language Models Beneficial? arXiv:2502.00674. https://arxiv.org/abs/2502.00674
4. When Agents Disagree: The Selection Bottleneck in Multi-Agent LLM Pipelines. (2026). arXiv:2603.20324. https://arxiv.org/abs/2603.20324
5. MMAD: Multi-Agent Mutual Awareness Debate. OpenReview. https://openreview.net/forum?id=0h3dbL6Iy3
6. Pitre, P., Ramakrishnan, N., & Wang, X. (2025). CONSENSAGENT. ACL Findings 2025. https://doi.org/10.18653/v1/2025.findings-acl.1141
7. Yao, B., et al. (2025). Peacemaker or Troublemaker. arXiv:2509.23055. https://arxiv.org/abs/2509.23055
