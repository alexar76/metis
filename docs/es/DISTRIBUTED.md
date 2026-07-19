# Cognitive Runtime distribuido

Este documento describe la arquitectura multi-servidor que permite ejecutar modelos individuales en distintas máquinas mientras el exoesqueleto los orquesta como un único «supercerebro» asegurado.

## Topología

```
                    ┌─────────────────────┐
                    │   Coordinador       │
                    │ (metis CLI /    │
                    │  CognitiveExoskel.) │
                    └──────────┬──────────┘
                               │ RPC seguro
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
    │  node-eu-1  │     │  node-us-1  │     │ node-asia-1 │
    │ qwen3:8b    │     │ phi4-mini   │     │ mistral:7b  │
    │ intent/     │     │ red_team/   │     │ synthesizer │
    │ proposer    │     │ refiner     │     │ aggregator  │
    └─────────────┘     └─────────────┘     └─────────────┘
```

- **Nodos trabajadores** alojan uno o más endpoints de modelos (`metis-node serve`).
- **Coordinador** ejecuta el Consejo de comprensión, MoA, verificador y enrutamiento — usa `RemoteLLMProvider` vía HTTP RPC cuando `distributed: true`.
- **Malla**: cualquier nodo puede añadirse/eliminarse; `NodeRegistry` gestiona descubrimiento, health checks y failover.

## Abstracción de nodo

Cada nodo se describe con `NodeDescriptor`:

| Campo | Propósito |
|-------|-----------|
| `id` | Identificador único del nodo |
| `url` | URL base (`https://eu1.example.com:8443`) |
| `models` | Modelos alojados en este nodo |
| `roles` | Roles del consejo/MoA |
| `api_key_env` | Nombre de variable env para bearer token (nunca texto plano en YAML) |

## Protocolo entre nodos

Los nodos trabajadores exponen:

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/metis/health` | GET | Bearer (si hay clave) | Liveness + lista de modelos/roles |
| `/metis/invoke` | POST | Bearer + HMAC opcional | RPC: completion en modelo local |
| `/v1/chat/completions` | POST | Bearer + HMAC opcional | Proxy compatible con OpenAI |

Esquemas de petición/respuesta en `metis/distributed/protocol.py` (Pydantic).

### Petición invoke

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

Límites de validación: máx. 100 mensajes, 100 KB por mensaje, temperature 0–2, max_tokens 1–100000.

## Seguridad

| Capa | Implementación |
|------|----------------|
| Transporte | TLS (`tls_verify` en config del clúster, predeterminado `true`) |
| Autenticación | Bearer token por nodo vía env `METIS_NODE_*_KEY` |
| Firma de peticiones | HMAC-SHA256 opcional con protección replay (ventana 5 min) |
| Comparación segura | `hmac.compare_digest` para tokens bearer y firmas |
| Secretos | Solo variables de entorno, nunca en archivos de config |
| Auditoría | Logs JSON estructurados sin contenido de prompts |
| Health endpoint | Requiere auth cuando hay clave API configurada |

Cabeceras con firma habilitada:

```
Authorization: Bearer <token>
X-Cognitive-Timestamp: <unix_seconds>
X-Cognitive-Signature: <hmac_sha256_hex>
```

## Configuración

### Config del clúster (`cluster_config.yaml`)

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

### Integración con runtime config

```yaml
distributed: true
cluster_config: cluster_config.yaml

council_models:
  - {name: parser_a, model: qwen3:8b, node_id: node-eu-1}
  - {name: parser_b, model: phi4-mini, node_id: node-us-1}
  - {name: red_team, model: qwen3:8b, node_id: node-us-1}
  - {name: synthesizer, model: mistral:7b, node_id: node-asia-1}
```

Con `distributed: true`, `create_provider()` resuelve `ModelSlot.node_id` → `NodeRegistry` → `RemoteLLMProvider`.

## Failover

1. `NodeRegistry.check_health()` sondea `/metis/health` en todos los nodos.
2. `RemoteLLMProvider` intenta el nodo primario, luego `failover_candidates()` con rol/modelo coincidente.
3. Nodos fallidos se marcan `unhealthy` hasta el siguiente health check exitoso.

## CLI

```bash
pip install -e ".[dev,distributed]"

export METIS_NODE_LOCAL_KEY=dev-key-1
metis-node serve --config node_config.yaml --production --port 8443

export METIS_NODE_LOCAL_KEY=dev-key-2
metis-node serve --config node_config.yaml --production --port 8444 --node-id node-2

metis-cluster status --config cluster_config.yaml
metis "Tu pregunta" --cluster cluster_config.yaml --production
```

## Mapa de módulos

| Archivo | Responsabilidad |
|---------|-----------------|
| `node.py` | `NodeDescriptor`, estado de salud |
| `registry.py` | Descubrimiento, health checks, failover |
| `remote_provider.py` | `LLMProvider` vía HTTP RPC |
| `coordinator.py` | Despacho paralelo entre nodos |
| `security.py` | Auth, HMAC, auditoría |
| `protocol.py` | Esquemas Pydantic |
| `server.py` | Servidor FastAPI del nodo |
| `cli.py` | Comandos `metis-node`, `metis-cluster` |

## Principios de diseño

1. **Sin acoplamiento directo a modelos** — los agentes hablan con nodos vía RPC.
2. **Misma API del exoesqueleto** — `Metis` no cambia; la distribución es un flag de config.
3. **Heterogeneidad por defecto** — distintos modelos en distintos nodos aumentan la diversidad del consejo.
4. **Fail closed en auth** — sin token válido se rechaza la petición cuando hay claves configuradas.
