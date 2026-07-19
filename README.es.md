# Metis — inicio rápido (ES)

**Metis** (μῆτις) — capa cognitiva distribuida sobre cualquier LLM.

🌐 Idioma: [English](README.md) · [Русский](README.ru.md) · **Español**

## Demo en vivo

Abre **[metis.modelmarket.dev](https://metis.modelmarket.dev/)** — estrella 3D, chat y grafo de cognición.

## Instalar

El paquete en PyPI se llama **`aimarket-metis`** (el nombre `metis` en PyPI es otro proyecto). El import y la CLI siguen siendo `metis`.

```bash
# PyPI
pip install aimarket-metis
pip install "aimarket-metis[dev,distributed]"

# Etiqueta de release en GitHub
pip install "aimarket-metis[distributed] @ git+https://github.com/alexar76/metis.git@v0.2.0"

# Clone / editable
git clone https://github.com/alexar76/metis.git && cd metis
pip install -e ".[dev,distributed]"

# Docker
docker compose up -d
```

## Primer comando

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,distributed]"
ollama pull qwen3:8b
metis "Explica sistemas multiagente" --model qwen3:8b --url http://localhost:11434/v1
```

## Más documentación

| Recurso | Enlace |
|---------|--------|
| Guía completa (ES) | [docs/es/README.md](docs/es/README.md) |
| Arquitectura · API · Deploy | [índice EN](README.md#documentation-index) |
| PyPI | [aimarket-metis](https://pypi.org/project/aimarket-metis/) |
| Demo | [metis.modelmarket.dev](https://metis.modelmarket.dev/) |
