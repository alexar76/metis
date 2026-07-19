# Inicio rápido

Ejecute Metis localmente en menos de cinco minutos.

## Requisitos

- Python 3.9+
- Un endpoint LLM (Ollama recomendado para desarrollo local)

## Instalación

```bash
git clone https://github.com/alexar76/metis.git
cd metis
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,distributed]"
```

## Primera consulta (Ollama)

```bash
ollama pull qwen3:8b
metis "Explica los sistemas multiagente" --model qwen3:8b --url http://localhost:11434/v1
```

## Primera consulta (API en la nube)

```bash
export METIS_API_KEY=sk-your-key
metis "Tu pregunta" -c config.production.yaml --production
```

## Servidor API compatible con OpenAI

```bash
pip install -e ".[distributed]"
export METIS_API_KEY=sk-your-secret   # opcional en dev
metis-serve -c config.yaml --port 8080
```

Prueba con curl:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-council",
    "messages": [{"role": "user", "content": "Explica los sistemas multiagente"}]
  }'
```

Verificación de salud:

```bash
curl http://localhost:8080/health
```

## Docker (stack distribuido)

```bash
cp config/docker.env.example .env   # editar secretos
docker compose up -d --build
curl http://localhost:8080/health
```

## Referencia CLI

| Comando | Ejemplo |
|---------|---------|
| `metis` | `metis "consulta" --model qwen3:8b --url http://localhost:11434/v1` |
| `metis-serve` | `metis-serve -c config.yaml --port 8080` |
| `metis-node` | `metis-node serve -c node_config.yaml --production --port 8443` |
| `metis-coordinator` | `metis-coordinator -c config/docker-runtime.yaml --port 8080` |
| `metis-cluster` | `metis-cluster status -c cluster_config.yaml` |

### Flags útiles

| Flag | Propósito |
|------|-----------|
| `-c config.yaml` | Cargar archivo de configuración |
| `--production` | Seguridad de producción (requiere `METIS_API_KEY`) |
| `--route fast` | Ruta rápida (una llamada LLM) |
| `--cluster cluster_config.yaml` | Clúster distribuido |

## Validación de configuración

```bash
metis config validate -c config.yaml
metis config show-modules -c config.yaml
```

## API Python

```python
import asyncio
from metis import Metis, RuntimeConfig
from metis.config import ProviderKind

config = RuntimeConfig(
    provider=ProviderKind.OLLAMA,
    base_model="qwen3:8b",
    base_url="http://localhost:11434/v1",
)
result = asyncio.run(Metis(config).run("Tu tarea"))
print(result.answer)
```

## Siguientes pasos

- [Configuration](../Configuration) — personalizar consejos, MoA, economía
- [IDE Integration](../IDE-Integration) — conectar VS Code Continue o Cursor
- [Architecture](../Architecture) — entender el pipeline
