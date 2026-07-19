# Metis Wiki

**Metis** (μῆτις) — распределённый когнитивный слой поверх любой LLM. Мультиагентный оркестратор рассуждений в экосистеме [alexar76](https://github.com/alexar76) AIMarket.

## Что делает Metis

Один LLM даёт одну интерпретацию задачи. Metis оборачивает любую модель в:

- **Understanding Council** — параллельные агенты → структурированный `TaskSpec`
- **DGPD** — Disagreement-Gated Pipeline Depth (пропуск дорогих слоёв при согласии)
- **Layered MoA** — propose → refine → aggregate
- **Agent loop** — план, действие, наблюдение, рефлексия с инструментами и MCP
- **Verifier** — судья проверяет ответ по контракту задачи
- **Economy** — учёт токенов, бюджеты, вебхуки
- **OpenAI-совместимый API** — `POST /v1/chat/completions`

## Быстрые ссылки

| Страница | Описание |
|----------|----------|
| [Architecture](../Architecture) | Архитектура (EN) |
| [Quick Start](Quick-Start) | Установка и первый запрос |
| [Configuration](../Configuration) | Конфигурация (EN) |
| [Docker Deployment](../Docker-Deployment) | Docker (EN) |
| [FAQ](FAQ) | Частые вопросы |

## Команды CLI

| Команда | Назначение |
|---------|------------|
| `metis` | Запрос через когнитивный стек |
| `metis-serve` | OpenAI-совместимый API (`/v1/chat/completions`) |
| `metis-node` | Рабочий узел кластера |
| `metis-coordinator` | Координатор кластера |
| `metis-cluster` | Проверка здоровья узлов |

## Документация в репозитории

- [docs/ru/README.md](https://github.com/alexar76/metis/blob/main/docs/ru/README.md)
- [docs/ru/ARCHITECTURE.md](https://github.com/alexar76/metis/blob/main/docs/ru/ARCHITECTURE.md)
- [docs/ru/DISTRIBUTED.md](https://github.com/alexar76/metis/blob/main/docs/ru/DISTRIBUTED.md)

## Языки

- [English](../Home)
- **Русский** (эта вики)
- [Español](../es/Home)

## Лицензия

MIT
