# Wiki de Metis

**Metis** (μῆτις) — capa cognitiva distribuida sobre cualquier LLM. Orquestador de razonamiento multiagente en el ecosistema [alexar76](https://github.com/alexar76) AIMarket.

## Qué hace Metis

Un solo LLM da una interpretación de la tarea. Metis envuelve cualquier modelo con:

- **Understanding Council** — agentes paralelos → `TaskSpec` estructurado
- **DGPD** — Disagreement-Gated Pipeline Depth (omite capas costosas al haber acuerdo)
- **Layered MoA** — propose → refine → aggregate
- **Agent loop** — planificar, actuar, observar, reflexionar con herramientas y MCP
- **Verifier** — juez valida la respuesta contra el contrato de tarea
- **Economy** — medición de tokens, presupuestos, webhooks
- **API compatible con OpenAI** — `POST /v1/chat/completions`

## Enlaces rápidos

| Página | Descripción |
|--------|-------------|
| [Architecture](../Architecture) | Arquitectura (EN) |
| [Quick Start](Quick-Start) | Instalación y primera consulta |
| [Configuration](../Configuration) | Configuración (EN) |
| [Docker Deployment](../Docker-Deployment) | Docker (EN) |
| [FAQ](FAQ) | Preguntas frecuentes |

## Comandos CLI

| Comando | Propósito |
|---------|-----------|
| `metis` | Ejecutar consulta a través del stack cognitivo |
| `metis-serve` | API compatible con OpenAI (`/v1/chat/completions`) |
| `metis-node` | Nodo trabajador distribuido |
| `metis-coordinator` | Coordinador del clúster |
| `metis-cluster` | Verificar salud de nodos |

## Documentación en el repositorio

- [docs/es/README.md](https://github.com/alexar76/metis/blob/main/docs/es/README.md)
- [docs/es/ARCHITECTURE.md](https://github.com/alexar76/metis/blob/main/docs/es/ARCHITECTURE.md)
- [docs/es/DISTRIBUTED.md](https://github.com/alexar76/metis/blob/main/docs/es/DISTRIBUTED.md)

## Idiomas

- [English](../Home)
- [Русский](../ru/Home)
- **Español** (esta wiki)

## Licencia

MIT
