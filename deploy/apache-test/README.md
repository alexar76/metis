# Apache test instance (parallel to nginx)

SKOPOS parses Apache access logs with the **same engine as nginx** (combined/common
format), and Apache log discovery now has **feature parity with nginx** — see
"Auto-discovery" below. This folder deploys a small **httpd** container for testing
without touching the production **metis-nginx** stack on ports 80/443.

## Topology

```
Internet ──▶ metis-nginx (:80 / :443)     ← production
localhost ─▶ metis-apache-test (:8088)    ← test only, SKOPOS Apache source
```

Both can run on the same host because they bind **different ports**.

## Deploy on metis

```bash
cd /opt/metis/deploy/apache-test   # sync this folder from the repo first
chmod +x deploy.sh
./deploy.sh
curl -sS http://127.0.0.1:8088/ | head
curl -sS http://127.0.0.1:8088/admin/ | head
tail -n 3 /opt/metis/deploy/apache-test/logs/access_log
```

Logs land at:

`/opt/metis/deploy/apache-test/logs/access_log`

## SKOPOS `servers.yaml` snippet

```yaml
  - name: metis
    source: ssh_http_access_log
    ssh:
      host: "<metis-host>"
      port: 22
      user: stats
      key_path: "~/.ssh/id_ed25519"
    nginx:
      access_log_path: "/var/log/nginx/access.log"
      auto_discover_logs: true
    apache:
      enabled: true
      access_log_path: "/opt/metis/deploy/apache-test/logs/access_log"
      auto_discover_logs: true
      # optional, same knobs as nginx:
      # access_log_paths: ["/var/log/apache2/api.example.com-access.log"]
      # auto_discover_docker_logs: false
      # docker_log_containers: []
```

Then run `skoposctl discover --config servers.yaml` — you should see both nginx and
`[file/apache]` sources for the server.

## Auto-discovery (parity with nginx)

With `apache.auto_discover_logs: true`, SKOPOS reads the host's Apache config just
like it reads nginx configs:

- Scans **`CustomLog`/`TransferLog`** directives across `sites-enabled`,
  `sites-available`, `conf-enabled`, `conf.d` — both Debian (`/etc/apache2`) and
  RHEL (`/etc/httpd`) layouts.
- Keeps **every** discovered path (they come only from access-log directives, never
  `ErrorLog`), including vhost logs without `access` in the filename.
- Expands `${APACHE_LOG_DIR}` → `/var/log/apache2`; skips piped loggers
  (`|/usr/bin/rotatelogs …`).
- Infers per-vhost host names from `example.com.access.log`,
  `example.com-access.log`, `example.com_access.log`, `example.com-access_log`.
- Docker HTTP containers can be discovered/tailed via
  `apache.auto_discover_docker_logs` / `apache.docker_log_containers`.

The bundled `httpd.conf` uses a single `CustomLog … combined`; to exercise
multi-vhost discovery, add extra `CustomLog` directives (e.g.
`CustomLog /usr/local/apache2/logs/api.example.com-access.log combined`) and
confirm they show up as separate `[file/apache]` sources.

## Notes

- Container image: `httpd:2.4-alpine`, config: `httpd.conf` (combined log format).
- Published only on `127.0.0.1:8088` by default — not exposed on the public IP.
- Remove: `docker rm -f metis-apache-test`
