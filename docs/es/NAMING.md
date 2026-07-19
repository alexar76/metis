# Nomenclatura: Metis

## Por qué Metis

**Metis** (griego: μῆτις, *mētis*) es la diosa del consejo, la sabiduría y el pensamiento profundo. El nombre refleja el diseño del proyecto:

- **Understanding Council** — varios asesores interpretan la tarea en paralelo
- **Cognición distribuida** — razonamiento en nodos y modelos
- **Sabiduría antes que velocidad** — enrutamiento, verificación y umbrales de confianza

## Encaje en el ecosistema

El ecosistema [alexar76](https://github.com/alexar76) usa nombres mitológicos:

| Proyecto | Mitología | Rol |
|----------|-----------|-----|
| **Helios** | Dios del sol | Observabilidad |
| **Argus** | Gigante de mil ojos | Agente de demanda / cliente |
| **Dioscuri** | Gemelos divinos | Servicios emparejados |
| **Metis** | Diosa del consejo | Capa de razonamiento y orquestación |

Metis está **encima** de los endpoints LLM y **debajo** de agentes como Argus.

## Nombres de modelos API

Los IDs OpenAI-compatibles siguen `metis-<ruta>`:

| Modelo | Ruta | Uso |
|--------|------|-----|
| `metis` | Auto | El clasificador elige la profundidad |
| `metis-fast` | Fast | Baja latencia |
| `metis-thinking` | Thinking | Razonamiento extendido |
| `metis-council` | Council | Consejo + MoA |
| `metis-agent` | Agent | Bucle de agente con herramientas |

## Variables de entorno

Prefijo `METIS_` (p. ej. `METIS_API_KEY`). Por un ciclo de release también se aceptan `SUPERBRAIN_*` y `COGNITIVE_*`.

## Rutas RPC distribuidas

- `GET /metis/health`
- `POST /metis/invoke`

Cabeceras de firma: `X-Metis-Timestamp`, `X-Metis-Signature`.

## API Python

```python
from metis import Metis, RuntimeConfig
```

Alias: `Superbrain`, `CognitiveExoskeleton`.
