# Troubleshooting

Common issues and fixes when running Metis.

## Installation

### `pip install` fails on Python version

Metis requires Python 3.9+. Check with `python3 --version`.

### `metis-serve` command not found

Install with distributed extras:

```bash
pip install -e ".[distributed]"
```

## CLI queries

### Connection refused to Ollama

```bash
# Ensure Ollama is running
ollama serve
ollama pull qwen3:8b
metis "test" --model qwen3:8b --url http://localhost:11434/v1
```

### `ERROR: Mock provider not allowed in production mode`

Remove `--production` for local dev, or switch `provider` from `mock` to `ollama` / `openai_compat` in config.

### Low confidence / clarification loop

The confidence gate is fail-closed. Either:
- Rephrase your query with more detail
- Lower `confidence_threshold` in config (not recommended for production)
- Use `--route fast` for simple factual questions

### Council diversity warnings

```
WARN: intent_parser_a and intent_parser_b share model+endpoint
```

Configure different models or endpoints per parser in `modules:` for best council quality.

## API server

### 401 Unauthorized

Production mode requires a valid Bearer token:

```bash
export METIS_API_KEY=sk-your-secret
curl -H "Authorization: Bearer $METIS_API_KEY" ...
```

### 429 Too Many Requests

Rate limit exceeded (default 60/min). Set `METIS_RATE_LIMIT_PER_MINUTE` or wait.

### 413 Request Entity Too Large

Max body size is 512 KB. Shorten your prompt or split the request.

### `/v1/chat/completions` returns empty or errors

1. Check health: `curl http://localhost:8080/health`
2. Validate config: `metis config validate -c config.yaml`
3. Check logs for provider errors (API key, base URL)
4. Verify the model endpoint is reachable

## Docker

### Coordinator unhealthy

```bash
docker compose logs coordinator
docker compose ps
```

Common causes:
- Nodes not started (`depends_on` — wait for node-a, node-b)
- Missing or wrong keys in `.env`
- Port 8080 already in use

### Node health check fails

Ensure `METIS_NODE_A_KEY` / `METIS_NODE_B_KEY` in `.env` match what nodes expect:

```bash
docker compose logs node-a
curl -H "Authorization: Bearer $METIS_NODE_A_KEY" http://localhost:8443/metis/health
```

### Ollama profile — models not found

```bash
docker compose --profile local-models up -d
docker exec -it metis-ollama ollama pull qwen3:8b
# Set OLLAMA_BASE_URL=http://ollama:11434/v1 in .env
```

### Permission errors with read-only containers

Containers use read-only root. Writable paths are `tmpfs` mounts and named volumes (`metis-memory`, `metis-config`). Do not write to `/app` at runtime.

## Distributed cluster

### `metis-cluster status` shows unhealthy nodes

1. Verify node is running: `metis-node serve ...`
2. Check Bearer token matches `api_key_env` in `cluster_config.yaml`
3. Verify HMAC secret is shared between coordinator and nodes
4. Check TLS: `tls_verify: true` requires valid certificates

### HMAC signature failures

Ensure `METIS_HMAC_SECRET` is identical on coordinator and all nodes. Clock skew must be within 5 minutes.

## MCP tools

### MCP server not connecting

1. Verify the MCP package is installed separately
2. Check `command` and `args` in `mcp_servers` config
3. Test the MCP server standalone before enabling in Metis

### Tool output seems ignored

Tool outputs are wrapped as untrusted data. The agent loop must be active (`metis-agent` route or agent route classification).

## Economy

### Budget exceeded / query rejected

Increase `session_budget_usd` or use `metis-fast` for cheaper queries. Check `economy.models` pricing table matches your actual providers.

## Config validation

```bash
metis config validate -c config.yaml
metis config show-modules -c config.yaml
```

Fix all `ERROR:` lines before production deployment. `WARN:` lines indicate suboptimal but functional config.

## Getting help

1. Check [FAQ](FAQ)
2. Review [docs/en/README.md](https://github.com/alexar76/metis/blob/main/docs/en/README.md)
3. Open an issue on [GitHub](https://github.com/alexar76/metis/issues) with config (redacted), error output, and reproduction steps
