# Справочник API Metis

**Версия 0.1.0** · OpenAI-совместимый HTTP API для когнитивного runtime Metis

Metis — **только API**, без встроенного чат-интерфейса. Клиенты подключаются через `POST /v1/chat/completions`, Python-класс `Metis` или CLI `metis`.

---

## Базовый URL

| Развёртывание | URL |
|---------------|-----|
| Локальная разработка | `http://localhost:8080` |
| Docker coordinator | `http://localhost:8080` |

---

## Аутентификация

```http
Authorization: Bearer sk-your-secret-key
```

Bearer-токен обязателен при `METIS_PRODUCTION=true` или заданном `METIS_API_KEY`.

| Переменная | Алиасы |
|------------|--------|
| `METIS_API_KEY` | `SUPERBRAIN_API_KEY`, `COGNITIVE_API_KEY` |

---

## Endpoints

### GET /health

Проверка состояния. **Аутентификация не требуется.**

```json
{"status": "ok", "service": "metis"}
```

```bash
curl -s http://localhost:8080/health
```

### GET /v1/models

Список моделей: `metis`, `metis-fast`, `metis-thinking`, `metis-council`, `metis-agent`.

```bash
curl -s http://localhost:8080/v1/models \
  -H "Authorization: Bearer $METIS_API_KEY"
```

### POST /v1/chat/completions

Синхронный JSON или SSE streaming (`"stream": true`).

| Поле | Тип | Обязательно | По умолчанию |
|------|-----|-------------|--------------|
| `model` | string | нет | `metis` |
| `messages` | array | **да** | — |
| `stream` | boolean | нет | `false` |

---

## Модели

| Модель | Маршрут | Описание |
|--------|---------|----------|
| `metis` | Авто (классификатор) | Router выбирает путь |
| `metis-fast` | `fast` | Один LLM completion |
| `metis-thinking` | `thinking` | Расширенное рассуждение |
| `metis-council` | `council` | Council + MoA + verifier |
| `metis-agent` | `agent` | Цикл агента с инструментами/MCP |

Legacy-алиасы: `superbrain-*`

---

## Примеры curl

### Council

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{"model":"metis-council","messages":[{"role":"user","content":"Объясни CAP-теорему"}]}'
```

### Streaming

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{"model":"metis-fast","stream":true,"messages":[{"role":"user","content":"2+2?"}]}'
```

---

## Коды ошибок

| Статус | Условие |
|--------|---------|
| `400` | Пустой `messages` |
| `401` | Неверный или отсутствующий Bearer |
| `413` | Тело запроса слишком большое |
| `503` | Metis не инициализирован |

---

## Связанная документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — когнитивный стек
- [DEPLOYMENT.md](DEPLOYMENT.md) — Docker и production
- [SECURITY.md](SECURITY.md) — модель угроз

Полная английская версия: [../en/API.md](../en/API.md)
