# Research Evidence

Honest mapping from Metis architecture to published research. Claims are benchmark-specific; production behavior may differ.

> Full digest: [docs/en/RESEARCH.md](https://github.com/alexar76/metis/blob/main/docs/en/RESEARCH.md)

## Summary

| Our claim | What research says | Confidence |
|-----------|-------------------|------------|
| ≥2 heterogeneous models beat scaling many copies of one | 2 diverse agents (L4) match/exceed 16 homogeneous (L1) on 7 reasoning benchmarks (7–8B models, vote/debate) | *proven* on cited benchmarks |
| Layered MoA improves answer quality | Open-source MoA reaches 65.1% LC win rate on AlpacaEval 2.0 vs 57.5% GPT-4 Omni | *proven* on instruction-following |
| Homogeneous scaling has diminishing returns | Accuracy gains per added identical agent collapse | *proven* on cited benchmarks |
| Diversity > raw agent count for reasoning | Heterogeneous configs beat homogeneous at same/lower count | *likely*, task-specific |
| Heterogeneous MoA is always best | **Often false** — Self-MoA beats mixed MoA on AlpacaEval 2.0 (+6.6 pp) | *proven* counterpoint |
| Verifier / judge matters | Diverse team + judge: 0.810 WR; MoA synthesis lost to baseline in 0/42 tasks | *likely* |
| Naive debate on small models fails | SLM debate can drop below single-agent via sycophantic drift | *proven* on 3–8B models |

**Legend:** *proven* = direct benchmark result; *likely* = supported but task/model-specific; *plausible* = architectural analogy, not A/B tested in this repo.

## Key papers

### 1. Agent Scaling via Diversity (Yang et al., 2026)

- arXiv: [2602.03794](https://arxiv.org/abs/2602.03794)
- Homogeneous scaling saturates; 2 fully diverse agents can match 16 homogeneous on reasoning benchmarks
- **Adopted:** `min_unique_council_models: 2`, heterogeneous cluster nodes

### 2. Mixture-of-Agents (Wang et al., ICLR 2025)

- arXiv: [2406.04692](https://arxiv.org/abs/2406.04692)
- Layered MoA: 65.1% on AlpacaEval 2.0 vs GPT-4o 57.5%
- **Adopted:** Three-layer propose → refine → aggregate pattern

### 3. Self-MoA counterpoint (Li et al., 2025)

- arXiv: [2502.00674](https://arxiv.org/abs/2502.00674)
- Single strong model + intra-model diversity often beats heterogeneous MoA
- **Adopted:** Document heterogeneity as *likely*, not guaranteed

### 4. When Agents Disagree (2026)

- arXiv: [2603.20324](https://arxiv.org/abs/2603.20324)
- Diversity helps with judge selection; weak aggregation loses to single model
- **Adopted:** Verifier/judge layer; caution on blind synthesis

### 5. MMAD — sycophantic drift (OpenReview)

- Naive debate on 3–8B SLMs causes accuracy collapse
- **Adopted:** Parallel council (not multi-round debate) + verifier

## Optimal network size defaults

| Setting | Default | Rationale |
|---------|---------|-----------|
| Minimum unique models | **2** | Yang et al.: full diversity at N=2 |
| Council roles | **5 slots** | Role diversity is weak supplement |
| MoA proposers | **3** parallel roles | MoA layered design precedent |
| Homogeneous replicas | **Avoid** beyond 2–4 | Diminishing returns when outputs correlate |

## What we extrapolate (not proven)

- That a 5-role Understanding Council with 2–3 models is "enough"
- That MoA gains transfer to TaskSpec-driven verification loops
- That DGPD agreement gating improves cost/quality tradeoffs in production

## Bibliography

1. Yang et al. (2026). *Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity.* arXiv:2602.03794
2. Wang et al. (2025). *Mixture-of-Agents Enhances Large Language Model Capabilities.* ICLR 2025. arXiv:2406.04692
3. Li et al. (2025). *Rethinking Mixture-of-Agents.* arXiv:2502.00674
4. *When Agents Disagree: The Selection Bottleneck.* arXiv:2603.20324
5. MMAD. OpenReview. https://openreview.net/forum?id=0h3dbL6Iy3

## Related

- [Architecture](Architecture) — how research maps to pipeline design
- [Configuration](Configuration) — `enforce_heterogeneous_agents`, DGPD settings
