# Benchmarks — Direct API vs Metis

Comparación de **una llamada directa al LLM** frente al **exoesqueleto completo de Metis** (consejo de comprensión, confidence gate, MoA, verificador) con los mismos modelos y prompts.

> [!IMPORTANT]
> **Metis es una puerta de riesgo / confianza — no un motor más rápido para trivia.**
> En tareas comprobables un modelo raw fuerte a menudo empata a Metis en precisión y gana en latencia.
> Usa Metis cuando necesitas un `verify_score` legible por máquina, captura de trampas, o un gate fail-closed antes de un paso autónomo.
> → [Dónde gana Metis](#dónde-gana-metis--leer-primero).

Motor canónico: **`deepseek-v4-pro`** (no el alias legado `deepseek-chat`).
Diversificadores OpenRouter: **MiniMax-M3**, **Kimi-K3**.

| Informe | Qué demuestra |
|---------|---------------|
| [`HEAD-TO-HEAD-2026-07-11.md`](../benchmarks/HEAD-TO-HEAD-2026-07-11.md) | Council Metis vs raw — **dónde gana Metis** |
| [`HEAD-TO-HEAD-2026-08-08.md`](../benchmarks/HEAD-TO-HEAD-2026-08-08.md) | Bake-off raw fresco: V4-Pro · MiniMax · Kimi-K3 |
| [`BENCHMARK-2026-07-11.md`](../benchmarks/BENCHMARK-2026-07-11.md) | Latencia por ruta + señal de confianza |

---

## Dónde gana Metis — leer primero

> Fuente: [HEAD-TO-HEAD-2026-07-11 § When to use](../benchmarks/HEAD-TO-HEAD-2026-07-11.md#when-to-use-metis--and-when-not) · [`bench-headtohead-2026-07-11.json`](../benchmarks/bench-headtohead-2026-07-11.json)

### Victoria de precisión medida (misma base)

24 ítems comprobables. HTTP real, sin mocks.

| Sistema | Overall | Trampas (6) | Latencia mediana |
|---------|:-------:|:-----------:|-----------------:|
| DeepSeek-V4-Pro **(raw)** | **96%** | 5/6 | ~0.3 s |
| MiniMax-M3 **(raw)** | 100% | **6/6** | ~6.6 s |
| **Metis (council sobre V4-Pro)** | **100%** | **6/6** | ~90 s |

**Ventaja de Metis:** el mismo V4-Pro pasó de **96% → 100%** al atrapar la trampa System-1
*«¿cuántos meses tienen exactamente 28 días?»* (**12**) que cuatro modelos frontier raw fallaron.
Además emite una señal de confianza que una llamada raw no tiene.

### Victoria all-star (olympiad duro)

| Config | Score |
|--------|:-----:|
| Mejor modelo fuerte en solitario | **90%** |
| **Council all-star Metis** | **100%** (resolvió el ítem que **ninguno** solo resolvió) |

### Lo que raw nunca emite

| Señal | Raw LLM | Metis |
|-------|:-------:|:-----:|
| Texto de respuesta | ✓ | ✓ |
| **`verify_score` / `verified`** | ✗ | ✓ |
| **`needs_clarification`** | ✗ | ✓ |

### Cuándo Metis **no** gana

| Situación | Resultado |
|-----------|-----------|
| Modelo ya fuerte en tareas comprobables | Misma precisión, **~15× más lento** |
| Modelos débiles en el council | Puede quedar **por debajo** del mejor débil solo (60% vs 90%) |

**Una línea:** Metis = **verificador + lift para un motor mid-tier — no un amplificador de basura.**

---

## Frontier bake-off 2026-08-08 (corrida real)

> HTTP en vivo 2026-08-08. 8 ítems de calibración. Solo **raw** (sin council en este refresh).
> [`HEAD-TO-HEAD-2026-08-08.md`](../benchmarks/HEAD-TO-HEAD-2026-08-08.md) · [`bench-frontier-2026-08-08.json`](../benchmarks/bench-frontier-2026-08-08.json)

| Sistema | Acc | trap | math | logic | Latencia mediana |
|---------|:---:|:---:|:---:|:---:|-----------------:|
| **MiniMax-M3** | **87.5%** (7/8) | **3/3** | 3/4 | 1/1 | 4.9 s |
| DeepSeek-V4-Pro | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 5.0 s |
| Kimi-K3 | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 11.8 s |
| DeepSeek-V4-Flash | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 2.5 s |
| Kimi-K2.6 | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 15.2 s |

Puntos ciegos complementarios: MiniMax atrapa la trampa de los meses; V4-Pro/Kimi el coin-change **242**.
Prod: **V4-Pro** + **MiniMax skeptic** + **V4-Flash** en asientos baratos.

```bash
export DEEPSEEK_API_KEY=...
export OPENROUTER_API_KEY=...
python3 metis/scripts/bench_frontier_bakeoff.py
```

---

## Inicio rápido (harness)

```bash
cd metis
pip install -e ".[dev]"
metis-benchmark run --mock --dataset simple --compare direct,metis

export DEEPSEEK_API_KEY=sk-...
metis-benchmark run --models deepseek-v4-pro --dataset all --compare direct,metis \
  --output reports/bench-$(date +%Y%m%d).md

export OPENROUTER_API_KEY=sk-or-...
metis-benchmark run --models deepseek-v4-pro,minimax-m3,kimi-k3 --dataset reasoning --compare direct
```

## Variables de entorno

| Variable | Proveedor |
|----------|-----------|
| `DEEPSEEK_API_KEY` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `OPENROUTER_API_KEY` | `minimax-m3`, `kimi-k3`, `kimi-k2.6` |
| `OPENAI_API_KEY` | `gpt-4o-mini` |
| _(ninguna)_ | `qwen3:8b` vía Ollama |

## CI

- `pytest -m benchmark` — tests mock sin claves.
- `benchmark.yml` — solo dispatch manual con secretos.
