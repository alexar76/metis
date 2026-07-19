# Quick Start

Get Metis running locally in under five minutes.

## Prerequisites

- Python 3.9+
- An LLM endpoint (Ollama recommended for local dev, or any OpenAI-compatible API)

## Install

```bash
git clone https://github.com/alexar76/metis.git
cd metis
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,distributed]"
```

## First query (Ollama)

```bash
ollama pull qwen3:8b
metis "Explain multi-agent systems" --model qwen3:8b --url http://localhost:11434/v1
```

## First query (cloud API)

```bash
export METIS_API_KEY=sk-your-key
metis "Your question" -c config.production.yaml --production
```

## Serve OpenAI-compatible API

```bash
pip install -e ".[distributed]"
export METIS_API_KEY=sk-your-secret   # optional in dev
metis-serve -c config.yaml --port 8080
```

Test with curl:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-council",
    "messages": [{"role": "user", "content": "Explain multi-agent systems"}]
  }'
```

Health check:

```bash
curl http://localhost:8080/health
```

## Docker (distributed stack)

```bash
cp config/docker.env.example .env   # edit secrets
docker compose up -d --build
curl http://localhost:8080/health
```

See [Docker Deployment](Docker-Deployment) for profiles and production checklist.

## CLI reference

| Command | Example |
|---------|---------|
| `metis` | `metis "query" --model qwen3:8b --url http://localhost:11434/v1` |
| `metis-serve` | `metis-serve -c config.yaml --port 8080` |
| `metis-node` | `metis-node serve -c node_config.yaml --production --port 8443` |
| `metis-coordinator` | `metis-coordinator -c config/docker-runtime.yaml --port 8080` |
| `metis-cluster` | `metis-cluster status -c cluster_config.yaml` |

### Useful flags

| Flag | Purpose |
|------|---------|
| `-c config.yaml` | Load configuration file |
| `--production` | Enable production security (requires `METIS_API_KEY`) |
| `--route fast` | Force fast path (single LLM call) |
| `--cluster cluster_config.yaml` | Use distributed cluster |

## Config validation

```bash
metis config validate -c config.yaml
metis config show-modules -c config.yaml
```

## Python API

```python
import asyncio
from metis import Metis, RuntimeConfig
from metis.config import ProviderKind

config = RuntimeConfig(
    provider=ProviderKind.OLLAMA,
    base_model="qwen3:8b",
    base_url="http://localhost:11434/v1",
)
result = asyncio.run(Metis(config).run("Your task"))
print(result.answer)
```

## Next steps

- [Configuration](Configuration) — customize councils, MoA, economy
- [IDE Integration](IDE-Integration) — connect VS Code Continue or Cursor
- [Architecture](Architecture) — understand the pipeline
