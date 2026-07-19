# Evidencia científica — sistemas multiagente LLM heterogéneos

Este documento relaciona investigación **verificada** con el diseño de metis. Las afirmaciones son específicas de benchmarks salvo que se indique lo contrario.

Versión completa en inglés: [RESEARCH.md (en)](../en/RESEARCH.md)

## Tabla resumen

| Artículo | Venue / año | Qué demostró realmente | Relevancia para metis |
|----------|-------------|------------------------|----------------------------|
| [Agent Scaling via Diversity](#1-escalado-de-agentes-vía-diversidad) | arXiv 2026 | Rendimientos decrecientes homogéneos; 2 agentes diversos ≈ 16 homogéneos en 7 benchmarks | `min_unique_council_models: 2` |
| [MoA](#2-mixture-of-agents-moa) | ICLR 2025 Spotlight | MoA en capas: 65,1% AlpacaEval 2.0 vs 57,5% GPT-4o | Pipeline MoA en capas |
| [Self-MoA](#3-self-moa-contraargumento) | arXiv 2025 | Un solo modelo fuerte a menudo supera MoA heterogéneo | La diversidad **no** siempre gana |
| [When Agents Disagree](#4-cuello-de-botella-de-selección) | arXiv 2026 | Diversidad ayuda con **juez**; síntesis MoA puede perder vs un modelo | Verificador + reintento |
| [MMAD](#5-mmad-deriva-sicofántica) | OpenReview | Debate ingenuo en SLM 3–8B → deriva, hasta ~10% precisión | Consejo paralelo, no debate |
| [CONSENSAGENT](#6-consensagent) | ACL Findings 2025 | Sicofancia en MAD aumenta coste | Prompts estructurados |
| [Peacemaker or Troublemaker](#7-peacemaker-or-troublemaker) | arXiv 2025 | Sicofancia colapsa el debate | Rol escéptico, red-team |

---

## 1. Escalado de agentes vía diversidad

**Cita:** Yingxuan Yang et al. *Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity.* arXiv:2602.03794, 2026. [PDF](https://arxiv.org/pdf/2602.03794) · [OpenReview](https://openreview.net/forum?id=9BN2W5BCfE)

**Demostrado:**

- Escalar agentes **homogéneos** muestra **rendimientos decrecientes** en siete benchmarks.
- La heterogeneidad aporta evidencia complementaria; métrica **K\***.
- Con Vote/Debate y modelos 7–8B: **2 agentes L4 ≥ 16 agentes L1** en configuraciones reportadas.
- Más fuerte en **razonamiento multi-paso** que en recuperación factual.

**Salvedades:** solo modelos open 7–8B; vote/debate, no MoA en capas; benchmarks, no producción.

**Adoptado:** ≥2 modelos distintos con `enforce_heterogeneous_agents: true`.

**Extrapolado:** que 5 roles del consejo bastan — **no probado** directamente.

---

## 2. Mixture-of-Agents (MoA)

**Cita:** Junlin Wang et al. ICLR 2025 (Spotlight). arXiv:2406.04692. [Paper ICLR](https://proceedings.iclr.cc/paper_files/paper/2025/file/5434be94e82c54327bb9dcaf7fca52b6-Paper-Conference.pdf)

**Demostrado:** MoA en capas con solo modelos open alcanza **65,1% LC win rate** en AlpacaEval 2.0 vs **57,5% GPT-4 Omni**.

**Salvedades:** benchmarks de instrucciones/chat; mayor coste y latencia.

**Adoptado:** proponer → refinar → agregar en `moa.py`.

---

## 3. Self-MoA (contraargumento)

**Cita:** Wenzhe Li et al. arXiv:2502.00674, 2025. [PDF](https://arxiv.org/pdf/2502.00674)

**Demostrado:** Self-MoA supera MoA heterogéneo en muchos escenarios (+6,6 pp AlpacaEval 2.0).

**Adoptado:** diversidad **probable**, no garantizada; temperatura en un solo modelo es diversidad **débil**.

---

## 4. Cuello de botella de selección

**Cita:** *When Agents Disagree.* arXiv:2603.20324, 2026. [PDF](https://arxiv.org/pdf/2603.20324)

**Demostrado (42 tareas):** equipo diverso + juez → WR 0,810; síntesis estilo MoA perdió vs baseline en **0/42** tareas según el panel de jueces.

**Adoptado:** verificador separado, no solo síntesis.

---

## 5. MMAD (deriva sicofántica)

**Cita:** *MMAD: Multi-Agent Mutual Awareness Debate.* [OpenReview](https://openreview.net/forum?id=0h3dbL6Iy3)

**Reportan:** debate ingenuo en SLM 3–8B causa **deriva sicofántica** (hasta ~10% precisión); MMAD (MToM) mitiga en GSM8K, CodeQA, etc.

**Salvedades:** debate multi-ronda; metis usa consejo **paralelo** sin ver respuestas ajenas en interpretación.

---

## 6–7. CONSENSAGENT y Peacemaker or Troublemaker

Ver [versión en inglés](../en/RESEARCH.md) para detalles. Resumen: la sicofancia en debate multiagente degrada resultados; prompts estructurados y roles críticos ayudan.

---

## Mapeo arquitectónico

| Afirmación metis | Evidencia | Confianza |
|-----------------------|-----------|-----------|
| ≥2 modelos heterogéneos | Agent Scaling, MoA | **Probable** |
| MoA en capas | ICLR 2025 | **Demostrado** en benchmarks chat |
| Consejo paralelo | Reduce riesgo de deriva de debate | **Plausible** |
| Verificador + reintento | Selection bottleneck | **Probable** |
| Más agentes homogéneos ≠ ganancia lineal | Agent Scaling | **Demostrado** (7 benchmarks, 7–8B) |
| MoA heterogéneo siempre mejor | Contradicho por Self-MoA | Depende de tarea y calidad |

## Bibliografía

Ver [RESEARCH.md (en)](../en/RESEARCH.md#bibliography).
