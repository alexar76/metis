# Бенчмарки — Direct API vs Metis

Сравнение **одного прямого вызова LLM** с полным **экзоскелетом Metis** (совет понимания, confidence gate, MoA, верификатор) на одних и тех же моделях и промптах.

> [!IMPORTANT]
> **Metis — gate риска / confidence, а не более быстрый движок для trivia.**
> На checkable задачах сильная raw-модель часто сравнивается с Metis по точности и выигрывает по latency.
> Metis нужен, когда нужен машинный `verify_score`, ловля ловушек или fail-closed gate перед автономным шагом.
> → [Где выигрывает Metis](#где-выигрывает-metis--читать-сначала).

Канонический движок: **`deepseek-v4-pro`** (не legacy `deepseek-chat`).
Диверсификаторы OpenRouter: **MiniMax-M3**, **Kimi-K3**.

| Отчёт | Что доказывает |
|-------|----------------|
| [`HEAD-TO-HEAD-2026-07-11.md`](../benchmarks/HEAD-TO-HEAD-2026-07-11.md) | Council Metis vs raw — **где Metis выигрывает** |
| [`HEAD-TO-HEAD-2026-08-08.md`](../benchmarks/HEAD-TO-HEAD-2026-08-08.md) | Свежий raw bake-off: V4-Pro · MiniMax · Kimi-K3 |
| [`BENCHMARK-2026-07-11.md`](../benchmarks/BENCHMARK-2026-07-11.md) | Latency по маршрутам + confidence signal |

---

## Где выигрывает Metis — читать сначала

> Источник: [HEAD-TO-HEAD-2026-07-11 § When to use](../benchmarks/HEAD-TO-HEAD-2026-07-11.md#when-to-use-metis--and-when-not) · [`bench-headtohead-2026-07-11.json`](../benchmarks/bench-headtohead-2026-07-11.json)

### Измеренный выигрыш по accuracy (тот же base)

24 checkable кейса. Живой HTTP, без моков.

| Система | Overall | Ловушки (6) | Median latency |
|---------|:-------:|:-----------:|---------------:|
| DeepSeek-V4-Pro **(raw)** | **96%** | 5/6 | ~0.3 s |
| MiniMax-M3 **(raw)** | 100% | **6/6** | ~6.6 s |
| **Metis (council на V4-Pro)** | **100%** | **6/6** | ~90 s |

**Преимущество Metis:** тот же V4-Pro **96% → 100%** — поймал ловушку «сколько месяцев имеют ровно 28 дней?» (**12**), которую четыре raw frontier-модели профукали. Плюс сигнал confidence, которого у raw-вызова нет.

### All-star на жёстком наборе

| Конфиг | Score |
|--------|:-----:|
| Лучшая одиночная сильная модель | **90%** |
| **Metis all-star council** | **100%** (решил задачу, которую никто один не решил) |

### Чего нет у raw

| Сигнал | Raw LLM | Metis |
|--------|:-------:|:-----:|
| Текст ответа | ✓ | ✓ |
| **`verify_score` / `verified`** | ✗ | ✓ |
| **`needs_clarification`** | ✗ | ✓ |

### Когда Metis **не** выигрывает

| Ситуация | Результат |
|----------|-----------|
| Уже сильная модель на checkable | Та же точность, **~15× медленнее** |
| Слабые модели в council | Может стать **хуже** лучшего одиночного (60% vs 90%) |

**Одной строкой:** Metis = **verifier + lift для mid-tier — не усилитель мусора.**

---

## Frontier bake-off 2026-08-08 (реальный прогон)

> Живой HTTP 2026-08-08. 8 калибровочных кейсов. Только **raw** (council в этом refresh не гоняли).
> [`HEAD-TO-HEAD-2026-08-08.md`](../benchmarks/HEAD-TO-HEAD-2026-08-08.md) · [`bench-frontier-2026-08-08.json`](../benchmarks/bench-frontier-2026-08-08.json)

| Система | Acc | trap | math | logic | Median latency |
|---------|:---:|:---:|:---:|:---:|---------------:|
| **MiniMax-M3** | **87.5%** (7/8) | **3/3** | 3/4 | 1/1 | 4.9 s |
| DeepSeek-V4-Pro | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 5.0 s |
| Kimi-K3 | **87.5%** (7/8) | 2/3 | **4/4** | 1/1 | 11.8 s |
| DeepSeek-V4-Flash | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 2.5 s |
| Kimi-K2.6 | 75.0% (6/8) | 2/3 | 3/4 | 1/1 | 15.2 s |

Комплементарные слепые зоны: MiniMax ловит month-trap; V4-Pro/Kimi — coin-change **242**.  
Прод: **V4-Pro** + **MiniMax skeptic** + **V4-Flash** на дешёвых ролях.

```bash
export DEEPSEEK_API_KEY=...
export OPENROUTER_API_KEY=...
python3 metis/scripts/bench_frontier_bakeoff.py
```

---

## Быстрый старт (harness)

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

## Переменные окружения

| Переменная | Провайдер |
|------------|-----------|
| `DEEPSEEK_API_KEY` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `OPENROUTER_API_KEY` | `minimax-m3`, `kimi-k3`, `kimi-k2.6` |
| `OPENAI_API_KEY` | `gpt-4o-mini` |
| _(нет)_ | `qwen3:8b` через Ollama |

## CI

- `pytest -m benchmark` — mock без ключей.
- `benchmark.yml` — только ручной запуск с секретами.
