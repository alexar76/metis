# FAQ

## General

### ¿Qué es Metis?

Metis (μῆτις) es una capa cognitiva distribuida sobre cualquier LLM. Orquesta razonamiento multiagente — consejos, MoA en capas, agent loop, verificación y medición económica — detrás de una API compatible con OpenAI.

### ¿Metis incluye interfaz de chat?

No. Metis es solo API. Use VS Code Continue, Cursor, `curl` o el CLI `metis`.

### ¿Qué proveedores LLM se soportan?

Cualquier endpoint compatible con OpenAI (Ollama, vLLM, LiteLLM, OpenAI, DeepSeek) más Anthropic nativo. Vea [Configuration](../Configuration).

### ¿En qué se diferencia de llamar un LLM directamente?

Un solo LLM da una interpretación. Metis ejecuta agentes de consejo en paralelo, controla la profundidad del pipeline con DGPD, sintetiza vía MoA en capas, verifica con un juez y mide costos.

## API

### ¿Cuál es el endpoint principal?

`POST /v1/chat/completions` — chat completions compatible con OpenAI.

### ¿Qué modelos puedo solicitar?

| Modelo | Comportamiento |
|--------|----------------|
| `metis` | Auto-enrutamiento |
| `metis-fast` | Ruta rápida, baja latencia |
| `metis-thinking` | Razonamiento extendido |
| `metis-council` | Consejo completo + MoA |
| `metis-agent` | Agent loop con herramientas |

### ¿Se requiere autenticación?

Opcional en desarrollo. Obligatoria en producción (`--production`).

## Configuración

### ¿Qué es DGPD?

**Disagreement-Gated Pipeline Depth** — omite capas costosas de MoA cuando los agentes del consejo están de acuerdo por encima del umbral. Palabras clave de alto riesgo fuerzan profundidad completa.

### ¿Cómo usar modelos diferentes por rol del consejo?

Sección `modules:` en `config.yaml`. Vea [Configuration](../Configuration).

### ¿Variables de entorno heredadas?

`SUPERBRAIN_*` y `COGNITIVE_*` se aceptan como alias por un ciclo de release. Prefiera `METIS_*`.

## Distribuido

### ¿Cómo ejecutar un clúster?

Use `metis-node` para workers, `metis-coordinator` para el coordinador, o `docker compose up`. Vea [Docker Deployment](../Docker-Deployment).

### ¿Cómo se protege el tráfico entre nodos?

TLS, Bearer auth (`METIS_NODE_*_KEY`), firma HMAC (`METIS_HMAC_SECRET`), rate limiting.

## Economía

### ¿Cómo funciona la facturación?

Metis mide tokens, aplica tablas de costos, aplica presupuestos de sesión y exporta uso vía webhook a AIMarket Hub.

### ¿Cómo reducir costos?

- `--route fast` o `metis-fast` para consultas simples
- `metis-council` solo para tareas ambiguas
- Modelos Ollama locales (costo API cero)
- Habilitar DGPD
- Establecer `session_budget_usd`

## Ecosistema

### ¿Cómo encaja Metis en alexar76?

Metis es la capa de razonamiento. Argus es el cliente de demanda. AIMarket Hub maneja medición pay-per-call.

### ¿Puedo usar herramientas MCP sin AIMarket?

Sí. Configure `mcp_servers` en `config.yaml` con cualquier servidor compatible MCP.

## Desarrollo

### ¿Cómo ejecutar tests?

```bash
pip install -e ".[dev,distributed]"
pytest -v
```

### ¿cognitive-runtime es el mismo proyecto?

No. `cognitive-runtime` fue un fork temprano. **Metis** es el proyecto canónico.

## Relacionado

- [Quick Start](Quick-Start)
- [Troubleshooting](../Troubleshooting)
- [Architecture](../Architecture)
