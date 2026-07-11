# Безопасность Metis

**Версия 0.1.0** · Модель угроз, митигации и защита от инъекций

---

## Модель угроз

| Угроза | Вектор | Митигация |
|--------|--------|-----------|
| **Prompt injection** | Сообщения пользователя, вывод инструментов/MCP | Скан паттернов, canary-токены, `<untrusted>`, принудительный L3 |
| **Role spoofing** | Маркеры `system:` во вводе | Удаление role markers, `validate_message_roles()` |
| **SSRF** | Веб-поиск, исходящий HTTP | `validate_url()`, проверка редиректов, блок private IP |
| **Несанкционированный API-доступ** | HTTP без auth | Bearer auth, rate limiting |
| **Flood** | Высокий объём запросов | Token bucket (60/мин, burst 10) |
| **Переполнение** | Большие тела/вывод | Лимиты размеров |
| **Подмена узла** | RPC между узлами | TLS, Bearer, HMAC, mTLS |

---

## Слои защиты

### Входной слой (`metis/security/injection.py`)

`sanitize_user_input()`:

1. Обрезка до `max_user_input_chars` (100 000)
2. Скан паттернов инъекций
3. Удаление role markers
4. Генерация canary (`SB-CANARY-<hex>`)

При `injection_detected: true` → DGPD принудительно включает **L3_FULL**.

### Промпт-слой

`build_system_prompt()` добавляет SECURITY BOUNDARY с canary.

`wrap_untrusted()` оборачивает вывод инструментов:

```xml
<untrusted source="tool_output">...</untrusted>
```

### Сетевой слой (`metis/security/ssrf.py`)

`safe_get()` / `safe_post()` — валидация URL на каждом редиректе (макс. 3), блок localhost и private IP.

### API-слой

| Контроль | По умолчанию |
|----------|--------------|
| Bearer auth | Обязателен в production |
| Rate limit | 60 req/мин, burst 10 |
| Тело запроса | 512 КБ (config) / 1 МБ (env) |
| CORS | Пустой список (запрет) |

---

## Паттерны инъекций

- `ignore previous instructions`
- `you are now ...`
- `<system>` / `system:`
- `jailbreak`, `ADMIN OVERRIDE`

Полный список: `metis/security/injection.py` → `_INJECTION_PATTERNS`

---

## Конфигурация

```yaml
security:
  max_user_input_chars: 100000
  max_tool_output_chars: 50000
  max_request_body_bytes: 512000
  enforce_injection_scan: true
  rate_limit:
    requests_per_minute: 60
    burst: 10
```

---

## Audit logging

`log_security_event()` — структурированный JSON **без** prompt, api_key, secret.

---

## Связанная документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — DGPD и слои безопасности
- [DEPLOYMENT.md](DEPLOYMENT.md) — Docker hardening

Полная английская версия: [../en/SECURITY.md](../en/SECURITY.md)
