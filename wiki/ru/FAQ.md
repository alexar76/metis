# FAQ

## Общие вопросы

### Что такое Metis?

Metis (μῆτις) — распределённый когнитивный слой поверх любой LLM. Оркестрирует мультиагентные рассуждения — советы, layered MoA, agent loop, верификацию и учёт экономики — через единый OpenAI-совместимый API.

### Есть ли встроенный чат-интерфейс?

Нет. Metis — только API. Используйте VS Code Continue, Cursor, `curl` или CLI `metis`.

### Какие провайдеры LLM поддерживаются?

Любой OpenAI-совместимый эндпоинт (Ollama, vLLM, LiteLLM, OpenAI, DeepSeek) и нативный Anthropic. См. [Configuration](../Configuration).

### Чем Metis отличается от прямого вызова LLM?

Один LLM даёт одну интерпретацию. Metis запускает параллельных агентов совета, управляет глубиной пайплайна через DGPD, синтезирует через layered MoA, верифицирует судьёй и учитывает стоимость.

## API

### Основной эндпоинт?

`POST /v1/chat/completions` — OpenAI-совместимые chat completions.

### Какие модели можно запрашивать?

| Модель | Поведение |
|--------|-----------|
| `metis` | Авто-маршрутизация |
| `metis-fast` | Быстрый путь, низкая задержка |
| `metis-thinking` | Расширенное рассуждение |
| `metis-council` | Полный совет + MoA |
| `metis-agent` | Agent loop с инструментами |

### Нужна ли аутентификация?

Опциональна в разработке. Обязательна в продакшене (`--production`).

## Конфигурация

### Что такое DGPD?

**Disagreement-Gated Pipeline Depth** — пропускает дорогие слои MoA, когда агенты совета согласны выше порога. Ключевые слова высокого риска принудительно включают полную глубину.

### Как использовать разные модели для ролей совета?

Секция `modules:` в `config.yaml`. См. [Configuration](../Configuration).

### Устаревшие переменные окружения?

`SUPERBRAIN_*` и `COGNITIVE_*` принимаются как алиасы на один релизный цикл. Предпочитайте `METIS_*`.

## Распределённый режим

### Как запустить кластер?

`metis-node` для воркеров, `metis-coordinator` для координатора, или `docker compose up`. См. [Docker Deployment](../Docker-Deployment).

### Как защищён трафик между узлами?

TLS, Bearer auth (`METIS_NODE_*_KEY`), HMAC-подпись (`METIS_HMAC_SECRET`), rate limiting.

## Экономика

### Как работает биллинг?

Metis считает токены, применяет таблицы стоимости, ограничивает бюджет сессии и экспортирует usage через webhook в AIMarket Hub.

### Как снизить стоимость?

- `--route fast` или `metis-fast` для простых запросов
- `metis-council` только для неоднозначных задач
- Локальные модели Ollama (нулевая стоимость API)
- Включите DGPD
- Установите `session_budget_usd`

## Экосистема

### Как Metis вписывается в alexar76?

Metis — слой рассуждений. Argus — клиент со стороны спроса. AIMarket Hub — pay-per-call метеринг.

### Можно ли использовать MCP без AIMarket?

Да. Настройте `mcp_servers` в `config.yaml` с любым MCP-совместимым сервером.

## Разработка

### Как запустить тесты?

```bash
pip install -e ".[dev,distributed]"
pytest -v
```

### cognitive-runtime — тот же проект?

Нет. `cognitive-runtime` — ранняя ветка. **Metis** — канонический проект.

## См. также

- [Quick Start](Quick-Start)
- [Troubleshooting](../Troubleshooting)
- [Architecture](../Architecture)
