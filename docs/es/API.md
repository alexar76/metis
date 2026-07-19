# Referencia API de Metis

**Versión 0.1.0** · API HTTP compatible con OpenAI para el runtime cognitivo Metis

Metis es **solo API** — sin interfaz de chat integrada. Los clientes se conectan mediante `POST /v1/chat/completions`, la clase Python `Metis` o el CLI `metis`.

---

## URL base

| Despliegue | URL |
|------------|-----|
| Desarrollo local | `http://localhost:8080` |
| Docker coordinator | `http://localhost:8080` |

---

## Autenticación

```http
Authorization: Bearer sk-your-secret-key
```

Token Bearer obligatorio cuando `METIS_PRODUCTION=true` o `METIS_API_KEY` está configurado.

| Variable | Alias |
|----------|-------|
| `METIS_API_KEY` | `SUPERBRAIN_API_KEY`, `COGNITIVE_API_KEY` |

---

## Endpoints

### GET /health

Comprobación de estado. **No requiere autenticación.**

```json
{"status": "ok", "service": "metis"}
```

```bash
curl -s http://localhost:8080/health
```

### GET /v1/models

Lista modelos: `metis`, `metis-fast`, `metis-thinking`, `metis-council`, `metis-agent`.

```bash
curl -s http://localhost:8080/v1/models \
  -H "Authorization: Bearer $METIS_API_KEY"
```

### POST /v1/chat/completions

Respuesta JSON síncrona o streaming SSE (`"stream": true`).

| Campo | Tipo | Requerido | Por defecto |
|-------|------|-----------|-------------|
| `model` | string | no | `metis` |
| `messages` | array | **sí** | — |
| `stream` | boolean | no | `false` |

---

## Modelos

| Modelo | Ruta | Descripción |
|--------|------|-------------|
| `metis` | Auto (clasificador) | El router elige la ruta |
| `metis-fast` | `fast` | Un solo completion LLM |
| `metis-thinking` | `thinking` | Razonamiento extendido |
| `metis-council` | `council` | Council + MoA + verificador |
| `metis-agent` | `agent` | Bucle de agente con herramientas/MCP |

Alias legacy: `superbrain-*`

---

## Ejemplos curl

### Council

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{"model":"metis-council","messages":[{"role":"user","content":"Explica el teorema CAP"}]}'
```

### Streaming

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{"model":"metis-fast","stream":true,"messages":[{"role":"user","content":"¿2+2?"}]}'
```

---

## Códigos de error

| Estado | Condición |
|--------|-----------|
| `400` | `messages` vacío |
| `401` | Bearer inválido o ausente |
| `413` | Cuerpo de solicitud demasiado grande |
| `503` | Metis no inicializado |

---

## Documentación relacionada

- [ARCHITECTURE.md](ARCHITECTURE.md) — stack cognitivo
- [DEPLOYMENT.md](DEPLOYMENT.md) — Docker y producción
- [SECURITY.md](SECURITY.md) — modelo de amenazas

Versión completa en inglés: [../en/API.md](../en/API.md)
