# Seguridad de Metis

**Versión 0.1.0** · Modelo de amenazas, mitigaciones y defensa contra inyección

---

## Modelo de amenazas

| Amenaza | Vector | Mitigación |
|---------|--------|------------|
| **Prompt injection** | Mensajes de usuario, salida de herramientas/MCP | Escaneo de patrones, tokens canary, `<untrusted>`, L3 forzado |
| **Role spoofing** | Marcadores `system:` en la entrada | Eliminación de role markers, `validate_message_roles()` |
| **SSRF** | Búsqueda web, HTTP saliente | `validate_url()`, validación de redirecciones, bloqueo de IP privadas |
| **Acceso API no autorizado** | HTTP sin auth | Bearer auth, rate limiting |
| **Flooding** | Alto volumen de solicitudes | Token bucket (60/min, burst 10) |
| **Desbordamiento** | Cuerpos/salida grandes | Límites de tamaño |
| **Suplantación de nodo** | RPC entre nodos | TLS, Bearer, HMAC, mTLS |

---

## Capas de defensa

### Capa de entrada (`metis/security/injection.py`)

`sanitize_user_input()`:

1. Truncar a `max_user_input_chars` (100 000)
2. Escanear patrones de inyección
3. Eliminar role markers
4. Generar canary (`SB-CANARY-<hex>`)

Con `injection_detected: true` → DGPD fuerza **L3_FULL**.

### Capa de prompt

`build_system_prompt()` añade SECURITY BOUNDARY con canary.

`wrap_untrusted()` envuelve la salida de herramientas:

```xml
<untrusted source="tool_output">...</untrusted>
```

### Capa de red (`metis/security/ssrf.py`)

`safe_get()` / `safe_post()` — validación de URL en cada redirección (máx. 3), bloqueo de localhost e IP privadas.

### Capa API

| Control | Por defecto |
|---------|-------------|
| Bearer auth | Obligatorio en producción |
| Rate limit | 60 req/min, burst 10 |
| Cuerpo de solicitud | 512 KB (config) / 1 MB (env) |
| CORS | Lista vacía (denegar) |

---

## Patrones de inyección

- `ignore previous instructions`
- `you are now ...`
- `<system>` / `system:`
- `jailbreak`, `ADMIN OVERRIDE`

Lista completa: `metis/security/injection.py` → `_INJECTION_PATTERNS`

---

## Configuración

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

`log_security_event()` — JSON estructurado **sin** prompt, api_key, secret.

---

## Documentación relacionada

- [ARCHITECTURE.md](ARCHITECTURE.md) — DGPD y capas de seguridad
- [DEPLOYMENT.md](DEPLOYMENT.md) — endurecimiento Docker

Versión completa en inglés: [../en/SECURITY.md](../en/SECURITY.md)
