# Docker Deployment

Run the full distributed Metis stack (coordinator + worker nodes) in containers.

## Quick start

```bash
cp config/docker.env.example .env   # edit secrets
docker compose up -d --build
curl http://localhost:8080/health
```

## Topology

```
Client → coordinator (:8080) → node-a (:8443) + node-b (:8444) → Cloud LLM APIs
                                      ↓ (optional)
                                   ollama (:11434, profile local-models)
```

| Service | Role | Port |
|---------|------|------|
| `coordinator` | HTTP API (`POST /v1/query`, `GET /health`, `/v1/chat/completions`) | 8080 |
| `node-a` | Worker node (parser, proposer) | 8443 (internal) |
| `node-b` | Worker node (red team, refiner) | 8444 (internal) |
| `ollama` | Local LLM backend (profile `local-models`) | 11434 |
| `redis` | Rate limiting / sessions (profile `redis`) | 6379 |

## Environment file

Edit `.env` (from `config/docker.env.example`):

```bash
METIS_API_KEY=your-coordinator-key
METIS_NODE_A_KEY=node-secret-a
METIS_NODE_B_KEY=node-secret-b
METIS_HMAC_SECRET=hmac-secret
METIS_COORDINATOR_PORT=8080
```

## Profiles

```bash
# Default: coordinator + nodes → external APIs via .env
docker compose up -d

# Include local Ollama
docker compose --profile local-models up -d
# Set OLLAMA_BASE_URL=http://ollama:11434/v1 in .env

# Production hardening (resource limits, logging, restart policies)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Scaling nodes

```bash
docker compose up -d --scale node-a=2
```

Scaled replicas share the internal DNS name `node-a`; the coordinator load-balances via `NodeRegistry` failover.

## Security defaults

Containers run with:

- Read-only root filesystem
- `cap_drop: ALL`
- `no-new-privileges`
- Health checks on coordinator and nodes

## Production checklist

- [ ] Copy `config/docker.env.example` → `.env` with strong random keys
- [ ] Set `METIS_API_KEY`
- [ ] Set `METIS_NODE_A_KEY` and `METIS_NODE_B_KEY`
- [ ] Set `METIS_HMAC_SECRET`
- [ ] Never enable `allow_test_provider` or mock provider
- [ ] Use `docker-compose.prod.yml` for resource limits and log rotation
- [ ] Terminate TLS at nginx/traefik
- [ ] Verify health: `curl http://localhost:8080/health`

## API usage

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -d '{
    "model": "metis-council",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Logs and debugging

```bash
docker compose logs -f coordinator
docker compose logs -f node-a
docker compose ps
```

## Related

- [Configuration](Configuration) — runtime and cluster YAML
- [Architecture](Architecture) — distributed security flow
- [Troubleshooting](Troubleshooting) — common Docker issues
