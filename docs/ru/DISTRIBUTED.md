# Распределённый Cognitive Runtime

Этот документ описывает мультисерверную архитектуру, при которой отдельные модели работают на разных машинах, а экзоскелет оркестрирует их как единый защищённый «супермозг».

## Топология

```
                    ┌─────────────────────┐
                    │   Координатор       │
                    │ (metis CLI /    │
                    │  CognitiveExoskel.) │
                    └──────────┬──────────┘
                               │ защищённый RPC
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
    │  node-eu-1  │     │  node-us-1  │     │ node-asia-1 │
    │ qwen3:8b    │     │ phi4-mini   │     │ mistral:7b  │
    │ intent/     │     │ red_team/   │     │ synthesizer │
    │ proposer    │     │ refiner     │     │ aggregator  │
    └─────────────┘     └─────────────┘     └─────────────┘
```

- **Рабочие узлы** хостят один или несколько эндпоинтов моделей (`metis-node serve`).
- **Координатор** запускает Совет понимания, MoA, верификатор и маршрутизацию — при `distributed: true` использует `RemoteLLMProvider` через HTTP RPC.
- **Сеть**: любой узел можно добавить/удалить; `NodeRegistry` обеспечивает обнаружение, health check и failover.

## Абстракция узла

Каждый узел описывается `NodeDescriptor`:

| Поле | Назначение |
|------|------------|
| `id` | Уникальный идентификатор узла |
| `url` | Базовый URL (`https://eu1.example.com:8443`) |
| `models` | Модели на этом узле |
| `roles` | Роли совета/MoA |
| `api_key_env` | Имя env-переменной для bearer-токена (не plaintext в YAML) |

## Межузловой протокол

Рабочие узлы предоставляют:

| Эндпоинт | Метод | Аутентификация | Описание |
|----------|-------|----------------|----------|
| `/metis/health` | GET | Bearer (если ключ задан) | Liveness + список моделей/ролей |
| `/metis/invoke` | POST | Bearer + опциональный HMAC | RPC: completion на локальной модели |
| `/v1/chat/completions` | POST | Bearer + опциональный HMAC | OpenAI-совместимый прокси |

Схемы запросов/ответов — в `metis/distributed/protocol.py` (Pydantic).

### Запрос invoke

```json
{
  "model": "qwen3:8b",
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "temperature": 0.7,
  "max_tokens": 4096,
  "request_id": "uuid",
  "caller_node": "coordinator"
}
```

Лимиты валидации: макс. 100 сообщений, 100 КБ на сообщение, temperature 0–2, max_tokens 1–100000.

## Безопасность

| Слой | Реализация |
|------|------------|
| Транспорт | TLS (`tls_verify` в конфиге кластера, по умолчанию `true`) |
| Аутентификация | Bearer-токен через `METIS_NODE_*_KEY` env |
| Подпись запросов | Опциональный HMAC-SHA256 с защитой от replay (окно 5 мин) |
| Сравнение токенов | `hmac.compare_digest` для bearer и подписей |
| Секреты | Только env-переменные, не в конфигах |
| Аудит | Структурированные JSON-логи без содержимого промптов |
| Health endpoint | Требует auth при настроенном API-ключе |

Заголовки при включённой подписи:

```
Authorization: Bearer <token>
X-Cognitive-Timestamp: <unix_seconds>
X-Cognitive-Signature: <hmac_sha256_hex>
```

## Конфигурация

### Конфиг кластера (`cluster_config.yaml`)

```yaml
coordinator:
  url: https://coord.example.com

nodes:
  - id: node-eu-1
    url: https://eu1.example.com:8443
    api_key_env: METIS_NODE_EU1_KEY
    models: [qwen3:8b]
    roles: [intent_parser, proposer]

security:
  tls_verify: true
  request_signing: true
  hmac_secret_env: METIS_HMAC_SECRET
```

### Интеграция с runtime config

```yaml
distributed: true
cluster_config: cluster_config.yaml

council_models:
  - {name: parser_a, model: qwen3:8b, node_id: node-eu-1}
  - {name: parser_b, model: phi4-mini, node_id: node-us-1}
  - {name: red_team, model: qwen3:8b, node_id: node-us-1}
  - {name: synthesizer, model: mistral:7b, node_id: node-asia-1}
```

При `distributed: true` функция `create_provider()` разрешает `ModelSlot.node_id` → `NodeRegistry` → `RemoteLLMProvider`.

## Failover

1. `NodeRegistry.check_health()` проверяет `/metis/health` на всех узлах.
2. `RemoteLLMProvider` пробует основной узел, затем `failover_candidates()` с подходящей ролью/моделью.
3. Упавшие узлы помечаются `unhealthy` до следующего успешного health check.

## CLI

```bash
pip install -e ".[dev,distributed]"

export METIS_NODE_LOCAL_KEY=dev-key-1
metis-node serve --config node_config.yaml --production --port 8443

export METIS_NODE_LOCAL_KEY=dev-key-2
metis-node serve --config node_config.yaml --production --port 8444 --node-id node-2

metis-cluster status --config cluster_config.yaml
metis "Ваш вопрос" --cluster cluster_config.yaml --production
```

## Карта модулей

| Файл | Ответственность |
|------|-----------------|
| `node.py` | `NodeDescriptor`, состояние здоровья |
| `registry.py` | Обнаружение, health check, failover |
| `remote_provider.py` | `LLMProvider` через HTTP RPC |
| `coordinator.py` | Параллельная диспетчеризация |
| `security.py` | Auth, HMAC, аудит |
| `protocol.py` | Pydantic-схемы |
| `server.py` | FastAPI-сервер узла |
| `cli.py` | Команды `metis-node`, `metis-cluster` |

## Принципы проектирования

1. **Нет прямой связи с моделями** — агенты общаются с узлами через RPC.
2. **Тот же API экзоскелета** — `Metis` не меняется; распределение — флаг конфига.
3. **Гетерогенность по умолчанию** — разные модели на разных узлах повышают разнообразие совета.
4. **Fail closed на auth** — без валидного токена запрос отклоняется, если ключи настроены.
