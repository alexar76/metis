# Observability

Structured JSON logging, per-request `trace_id`, module spans, audit log with optional hash chain, and reliability (retries + circuit breakers).

## CLI

```bash
metis logs trace <trace_id>
metis logs tail -n 20
metis logs stats
```

## Config

```yaml
observability:
  log_content: redacted
  trace_dir: data/traces
  reliability:
    max_retries: 3
    circuit_breaker:
      enabled: true
```

See [docs/en/OBSERVABILITY.md](../docs/en/OBSERVABILITY.md).
