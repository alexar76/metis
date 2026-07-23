# SKOPOS test deployment on metis

Test instance of **SKOPOS** on the Metis node — PostgreSQL + dashboard on **localhost:8501** (not public by default).

## Stack

```
skopos.modelmarket.dev → metis-nginx → 127.0.0.1:8501 (Streamlit UI)
                                      → 127.0.0.1:8502 (/healthz JSON)
                                      → 127.0.0.1:8502 (/agent/* assistant chat)
localhost:8501  →  metis-skopos (Streamlit)
                      ├─ PostgreSQL (metis-skopos-postgres)
                      ├─ SSH → host (security scan)
                      ├─ docker logs → metis-nginx
                      └─ file tail → apache-test access_log
metis-nginx     →  :80 / :443 (unchanged)
metis-apache-test → :8088 (optional log source)
```

## Deploy from laptop (monorepo)

```bash
cd metis/deploy/skopos-test
chmod +x remote-sync.sh deploy.sh
./remote-sync.sh
```

First run generates `/opt/skopos-test/deploy/.env` with random dashboard + Postgres passwords.

`remote-sync.sh` also syncs the static landing to metis nginx and, when `GH_PAT` or `GITHUB_TOKEN` is set, publishes it to **GitHub Pages** ([alexar76.github.io/skopos](https://alexar76.github.io/skopos/)) via `./scripts/publish_all_repos.sh --satellite skopos`. Disable with `SKOPOS_PAGES_PUBLISH=0`.

Manual Pages publish:

```bash
./scripts/build_skopos_landing.sh
./scripts/publish_all_repos.sh --satellite skopos
```

## Open UI locally

```bash
ssh -L 8501:127.0.0.1:8501 root@<metis-host>
# browser: http://localhost:8501
```

Password on server:

```bash
grep SKOPOS_DASHBOARD_PASSWORD /opt/skopos-test/deploy/.env
```

## Manual on-server

```bash
# after rsync of skopos/ to /opt/skopos-test/app
cd /opt/skopos-test/deploy
cp .env.example .env   # or let deploy.sh generate
./deploy.sh
```

## Useful commands

```bash
cd /opt/skopos-test/deploy
docker compose logs -f skopos
docker compose exec skopos python skoposctl.py discover
docker compose exec skopos python skoposctl.py collect
docker compose exec skopos python skoposctl.py security-scan
```

## Files

| Path on metis | Role |
|---------------|------|
| `/opt/skopos-test/app/` | SKOPOS source (rsync) |
| `/opt/skopos-test/deploy/` | compose, servers.yaml, .env |
| `/opt/metis/deploy/apache-test/` | Apache test logs for SKOPOS |

## GeoIP (countries on map & filters)

**Default (no signup):** HTTP lookups via [geojs.io](https://www.geojs.io/) and [ipwho.is](https://ipwho.is/) — works out of the box on deploy.

**Optional offline boost:** MaxMind GeoLite2-Country (~9 MB) when you have a license key:

1. Create a free MaxMind account: https://www.maxmind.com/en/geolite2/signup  
2. Generate a **license key** (Account → Manage License Keys)  
3. Add to `/opt/skopos-test/deploy/.env`:

```bash
MAXMIND_LICENSE_KEY=your_key_here
SKOPOS_GEOIP_API_FALLBACK=0   # offline-only once MMDB is installed
```

4. Uncomment in `servers.yaml`: `geoip_mmdb_path: "/app/geoip/GeoLite2-Country.mmdb"`  
5. Re-run `./deploy.sh`

## Database

This stack uses **PostgreSQL only** (no SQLite in production):

| Setting | Value |
|---------|--------|
| Container | `metis-skopos-postgres` |
| Host (from skopos container) | `postgres:5432` |
| Database | `skopos` |
| User | `skopos` |
| Host port | **not published** (internal Docker network only) |

Credentials live in `/opt/skopos-test/deploy/.env`:

```bash
grep SKOPOS_POSTGRES /opt/skopos-test/deploy/.env
grep SKOPOS_DASHBOARD_PASSWORD /opt/skopos-test/deploy/.env
```

Hardening (SCRAM, pg_hba limited to `172.19.0.0/16`, revoke PUBLIC grants):

```bash
cd /opt/skopos-test/deploy && ./postgres-harden.sh
```

## Notes

- UI binds **127.0.0.1:8501** only — use SSH tunnel or add nginx reverse proxy for public access.
- `servers.yaml` uses `host.docker.internal` for SSH probes of the Metis host.
- Production recommendation: keep **PostgreSQL** (already default in this stack).
