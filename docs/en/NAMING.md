# Naming: Metis

## Why Metis

**Metis** (Greek: μῆτις, *mētis*) is the goddess of counsel, wisdom, and deep thought in Greek mythology. The name reflects what this project does:

- **Understanding Council** — multiple advisors interpret a task in parallel
- **Distributed cognition** — reasoning spread across nodes and models
- **Wisdom over speed** — routing, verification, and confidence gates before answering

## Ecosystem fit

The [alexar76](https://github.com/alexar76) ecosystem uses mythological names for infrastructure layers:

| Project | Mythology | Role |
|---------|-----------|------|
| **Helios** | Sun god | Observability / light on the system |
| **Argus** | All-seeing giant | Demand-side agent / client |
| **Dioscuri** | Divine twins | Paired services |
| **Metis** | Goddess of counsel | Reasoning & orchestration layer |

Metis sits **above** raw LLM endpoints and **below** demand agents like Argus.

## API model naming

OpenAI-compatible model IDs follow `metis-<route>`:

| Model | Route | Use case |
|-------|-------|----------|
| `metis` | Auto (classifier) | Default — router picks depth |
| `metis-fast` | Fast | Low latency, single pass |
| `metis-thinking` | Thinking | Extended reasoning |
| `metis-council` | Council | Understanding Council + MoA |
| `metis-agent` | Agent | Tool-using agent loop |

The bare name `metis` lets the internal classifier choose the route. Suffix models **force** a pipeline depth for IDE clients (Continue, Cursor, etc.).

## Environment variables

All configuration uses the `METIS_` prefix (e.g. `METIS_API_KEY`, `METIS_PRODUCTION`, `METIS_NODE_A_KEY`).

For one release cycle, `SUPERBRAIN_*` and `COGNITIVE_*` are still accepted as aliases.

## Distributed RPC paths

Worker nodes expose:

- `GET /metis/health`
- `POST /metis/invoke`

Signed requests use `X-Metis-Timestamp` and `X-Metis-Signature` headers.

## Python API

```python
from metis import Metis, RuntimeConfig

brain = Metis(RuntimeConfig())
result = await brain.run("Your task")
```

Backward-compatible aliases: `Superbrain`, `CognitiveExoskeleton`.
