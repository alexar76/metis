# Metis public deployment (reverse proxy + TLS)

The live demo node serves **https://metis.modelmarket.dev** (Metis landing + API) and
**https://skopos.modelmarket.dev** (SKOPOS dashboard). This folder holds the reproducible nginx config.

## Topology

```
Internet ──▶ metis-nginx (nginx:alpine, :80/:443)
                │  metis.modelmarket.dev
                │  ├─ /            → static landing  (/var/www/metis-landing)
                │  ├─ /v1/…        → metis:8080      (OpenAI-compatible + ecosystem)
                │  ├─ /health      → metis:8080
                │  └─ /aimarket/…  → metis:8080      (paid ecosystem invoke)
                │
                │  skopos.modelmarket.dev
                │  ├─ /            → static SKOPOS landing  (/var/www/metis-landing/skopos)
                │  ├─ /app/        → metis-skopos:8501   (Streamlit dashboard)
                │  └─ /healthz     → metis-skopos:8502   (public JSON status)
                │
                └──▶ metis (metis-serve, :8080)  ── DeepSeek provider
                     metis-skopos (SKOPOS stack on metisnet)
```

Both Metis and SKOPOS upstreams must be on the **`metisnet`** docker network so nginx
can reach them by container name. Only 80/443 are published to the host.

## SKOPOS vhost (`skopos.modelmarket.dev`)

Defined at the bottom of [`nginx.conf`](nginx.conf). Deploy the app stack first:

```bash
cd metis/deploy/skopos-test && ./remote-sync.sh
docker network connect metisnet metis-skopos   # idempotent if compose already attaches metisnet
```

Issue TLS (once DNS `A` → node IP):

```bash
docker run --rm -v /opt/metis/deploy/letsencrypt:/etc/letsencrypt \
  -v /var/www/certbot:/var/www/certbot certbot/certbot certonly --webroot \
  -w /var/www/certbot -d skopos.modelmarket.dev --agree-tos --register-unsafely-without-email --non-interactive
docker exec metis-nginx nginx -s reload
```

Smoke: `curl -fsS https://skopos.modelmarket.dev/healthz`

Full stack docs: [`skopos-test/README.md`](skopos-test/README.md).

## API container (metis-serve)

The image's default `CMD` is `metis-coordinator --production` (the distributed
coordinator), so the public single-node demo **must** override it with the explicit
`metis-serve` command, run in **non-production** mode (the demo is intentionally
keyless — `METIS_PRODUCTION=true`, baked into the image, would make the C4 fail-closed
auth reject every keyless call), and mount a **persistent** data dir so the
KnowledgeStore/memory survive a container recreate:

```bash
mkdir -p /opt/metis/data && chown -R 1000:1000 /opt/metis/data   # store persists here
docker build -t metis:latest /opt/metis
docker rm -f metis 2>/dev/null || true
docker run -d --name metis --restart unless-stopped \
  --network metisnet -p 127.0.0.1:8080:8080 \
  -e METIS_PRODUCTION=false \
  -v /opt/metis/deploy/prod.yaml:/app/config/prod.yaml:ro \
  -v /opt/metis/data:/app/data \
  metis:latest metis-serve --host 0.0.0.0 --port 8080 --config /app/config/prod.yaml
docker network connect bridge metis   # outbound already works via metisnet; matches original
```

Then seed the reproducible ecosystem knowledge into the persistent store (idempotent):

```bash
docker exec -i metis python3 - data/knowledge < scripts/seed_ecosystem_knowledge.py
```

Miss any of these and the symptoms are: `metis-coordinator` default → `/v1/verify`
404s; `METIS_PRODUCTION=true` + no key → every call 401s; no data mount → a recreate
silently resets `knowledge_entries` to 0.

## First-time setup

1. **DNS** — point an `A` record at the node (e.g. `metis.modelmarket.dev → <metis-host-ip>`).
2. **Landing** — sync `docs/landing/` to `/var/www/metis-landing/`.
3. **Config** — copy `nginx.conf` to `/opt/metis/deploy/nginx.conf`.
4. **Run nginx** (HTTP first, so the ACME challenge is reachable):

   ```bash
   mkdir -p /var/www/certbot /opt/metis/deploy/letsencrypt
   docker run -d --name metis-nginx --restart unless-stopped \
     --network metisnet -p 80:80 -p 443:443 \
     -v /var/www/metis-landing:/usr/share/nginx/html:ro \
     -v /opt/metis/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
     -v /var/www/certbot:/var/www/certbot:ro \
     -v /opt/metis/deploy/letsencrypt:/etc/letsencrypt:ro \
     nginx:alpine
   ```

5. **Issue the certificate** (webroot method — no host packages needed; apt-free):

   ```bash
   docker run --rm \
     -v /opt/metis/deploy/letsencrypt:/etc/letsencrypt \
     -v /var/www/certbot:/var/www/certbot \
     certbot/certbot certonly --webroot -w /var/www/certbot \
     -d metis.modelmarket.dev --agree-tos --register-unsafely-without-email --non-interactive
   ```

6. **Reload** nginx to pick up the cert: `docker exec metis-nginx nginx -s reload`.

## Auto-renewal

Weekly cron on the host (Let's Encrypt certs last 90 days):

```cron
0 3 * * 1 docker run --rm -v /opt/metis/deploy/letsencrypt:/etc/letsencrypt -v /var/www/certbot:/var/www/certbot certbot/certbot renew --webroot -w /var/www/certbot --quiet && docker exec metis-nginx nginx -s reload
```

Test it without touching the live cert: append `--dry-run` to the `renew` call.

## Notes

- The bare IP keeps serving over plain HTTP (the cert only covers the domain), so
  `http://<ip>/` still works for smoke tests; the domain always upgrades to HTTPS.
- Rate limiting (`30 r/m` per IP, small bursts) protects the API endpoints.
- **Apache test (SKOPOS):** optional `metis-apache-test` on `127.0.0.1:8088` — see [`apache-test/README.md`](apache-test/README.md). Does not replace nginx on 80/443.
- The API container never sees TLS — nginx terminates it. Keep `metis` bound to
  the docker network only (do **not** publish :8080 to the host).
- **Base model (reasoning)** — `prod.yaml` sets `base_model: deepseek-v4-pro`, a reasoning
  model that returns the answer in `content` and its chain-of-thought separately in
  `reasoning_content`. The provider handles this transparently: it keeps a token-budget
  floor for reasoning models and retries with a larger budget if a tight cap starves the
  answer, so `content` is reliably clean and complete (never empty, never raw CoT). Council
  on v4-pro runs ~60–70s (under the 120s API / 300s stream timeouts).
- **Self-knowledge (identity)** — set `identity:` in `prod.yaml` (or `METIS_IDENTITY` env) to a
  block describing what Metis is, its ecosystem, services, tools and use-cases. It is prepended to
  the system prompt of **every** route (fast/thinking/council/agent/vision) via one provider-layer
  hook, so the model always answers accurately about itself instead of "I'm a generic assistant".
  Empty by default (standalone unchanged). The canonical block lives in `config.production.yaml`.
- **Vision (multimodal)** — DeepSeek's API is text-only, so image understanding needs a
  separate vision-capable slot. Wire it in `prod.yaml` (the reasoning council stays on
  DeepSeek; only perception uses this model):

  ```yaml
  vision_timeout_seconds: 30
  vision_retries: 3            # free vision endpoints are flaky — retry within the budget
  modules:
    vision:
      provider: openai_compat
      model: nvidia/nemotron-nano-12b-v2-vl:free   # free VL model on OpenRouter
      base_url: https://openrouter.ai/api/v1
      api_key: sk-or-...                            # OpenRouter key (server-only, never committed)
      supports_vision: true
      temperature: 0.2
      extra_headers:                                # OpenRouter free-tier priority
        HTTP-Referer: https://metis.modelmarket.dev
        X-Title: Metis
  ```

  The vision model "sees" the image → its (untrusted-sanitized) observation feeds the
  DeepSeek council. If the vision call is rate-limited/slow it retries within
  `vision_timeout_seconds`, then fails over to an honest "couldn't read the image" note —
  the text pipeline is never blocked.
- **Deliberate-by-default demo** — `prod.yaml` sets `default_route: council` and the
  landing defaults its "Deep think" toggle **on** (sends `route: council`), so the
  cognition panel shows the *full* council trace on the first query. Note the
  classifier only runs when `default_route: council` *and* no explicit route is sent
  (toggle off) — otherwise it short-circuits to `default_route`. Trade-off: every
  default query is a full council run (~10s, ~12 LLM calls); it's rate-limited, and
  a visitor can untick "Deep think" for smart/fast auto-routing.
- **CORS** — the deployed landing is same-origin (nginx serves it and proxies the
  API under one host), so CORS isn't needed for it. But the demo is also meant to
  work when the landing is opened from another origin (a local `file://`, an embed):
  set `security.cors_origins: ["*"]` in `prod.yaml` so a browser on any origin can
  call the public, rate-limited, keyless demo endpoints, and restart `metis`. The
  landing defaults its endpoint to `https://metis.modelmarket.dev` whenever it is
  **not** served from that host, so a local copy talks to the live node (real, not
  demo) rather than a missing `localhost`.
