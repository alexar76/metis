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

Con `injection_detected: true` → Metis **rechaza de forma dura** la petición (`INJECTION_REFUSAL`), sin MoA / verifier.

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
| Bearer auth | Obligatorio por defecto, incluso en loopback; TCP sin clave requiere `METIS_LOCAL_RELAY=1` explícito |
| Rate limit | 60 req/min, burst 10 |
| Cuerpo de solicitud | 512 KB (config) / 1 MB (env) |
| CORS | Lista vacía (denegar) |

`METIS_LOCAL_RELAY=1` confía en clientes TCP locales, incluidos proxies y túneles con el mismo UID. Sin las tablas de sockets de Linux también requiere `METIS_LOCAL_UNVERIFIED=1`. Ambos están desactivados por defecto y no omiten una clave configurada ni el modo production. Se recomienda `METIS_API_KEY`: el nombre del proceso no demuestra que la petición sea directa.

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
