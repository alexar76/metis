# Быстрый старт

Запустите Metis локально за несколько минут.

## Требования

- Python 3.9+
- LLM-эндпоинт (рекомендуется Ollama для локальной разработки)

## Установка

```bash
git clone https://github.com/alexar76/metis.git
cd metis
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,distributed]"
```

## Первый запрос (Ollama)

```bash
ollama pull qwen3:8b
metis "Объясни мультиагентные системы" --model qwen3:8b --url http://localhost:11434/v1
```

## Первый запрос (облачный API)

```bash
export METIS_API_KEY=sk-your-key
metis "Ваш вопрос" -c config.production.yaml --production
```

## OpenAI-совместимый API-сервер

```bash
pip install -e ".[distributed]"
export METIS_API_KEY=sk-your-secret   # опционально в dev
metis-serve -c config.yaml --port 8080
```

Проверка через curl:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-council",
    "messages": [{"role": "user", "content": "Объясни мультиагентные системы"}]
  }'
```

Проверка здоровья:

```bash
curl http://localhost:8080/health
```

## Docker (распределённый стек)

```bash
cp config/docker.env.example .env   # отредактируйте секреты
docker compose up -d --build
curl http://localhost:8080/health
```

## Справочник CLI

| Команда | Пример |
|---------|--------|
| `metis` | `metis "запрос" --model qwen3:8b --url http://localhost:11434/v1` |
| `metis-serve` | `metis-serve -c config.yaml --port 8080` |
| `metis-node` | `metis-node serve -c node_config.yaml --production --port 8443` |
| `metis-coordinator` | `metis-coordinator -c config/docker-runtime.yaml --port 8080` |
| `metis-cluster` | `metis-cluster status -c cluster_config.yaml` |

### Полезные флаги

| Флаг | Назначение |
|------|------------|
| `-c config.yaml` | Загрузить конфигурацию |
| `--production` | Продакшен-безопасность (требует `METIS_API_KEY`) |
| `--route fast` | Быстрый путь (один вызов LLM) |
| `--cluster cluster_config.yaml` | Распределённый кластер |

## Валидация конфигурации

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
result = asyncio.run(Metis(config).run("Ваша задача"))
print(result.answer)
```

## Дальше

- [Configuration](../Configuration) — настройка советов, MoA, economy
- [IDE Integration](../IDE-Integration) — VS Code Continue, Cursor
- [Architecture](../Architecture) — архитектура пайплайна
