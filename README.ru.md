# Metis — быстрый старт (RU)

**Metis** (μῆτις) — распределённый когнитивный слой поверх любой LLM.

🌐 Язык: [English](README.md) · **Русский** · [Español](README.es.md)

## Живое демо

Открой **[metis.modelmarket.dev](https://metis.modelmarket.dev/)** — 3D-звезда, чат и граф когниции.

## Установка

Пакет на PyPI называется **`aimarket-metis`** (имя `metis` на PyPI — другой проект). Импорт и CLI остаются `metis`.

```bash
# PyPI
pip install aimarket-metis
pip install "aimarket-metis[dev,distributed]"

# Тег релиза на GitHub
pip install "aimarket-metis[distributed] @ git+https://github.com/alexar76/metis.git@v0.2.0"

# Clone / editable
git clone https://github.com/alexar76/metis.git && cd metis
pip install -e ".[dev,distributed]"

# Docker
docker compose up -d
```

## Первая команда

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,distributed]"
ollama pull qwen3:8b
metis "Объясни мультиагентные системы" --model qwen3:8b --url http://localhost:11434/v1
```

## Дальше

| Ресурс | Ссылка |
|--------|--------|
| Полное руководство (RU) | [docs/ru/README.md](docs/ru/README.md) |
| Архитектура · API · Deploy | [индекс EN](README.md#documentation-index) |
| PyPI | [aimarket-metis](https://pypi.org/project/aimarket-metis/) |
| Демо | [metis.modelmarket.dev](https://metis.modelmarket.dev/) |
