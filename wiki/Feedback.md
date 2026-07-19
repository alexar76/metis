# Feedback API

Submit ratings for completed traces to improve the knowledge store.

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"trace_id": "abc123", "rating": 5, "comment": "helpful"}'
```

- `rating`: 1–5
- Auth required when `METIS_PRODUCTION=1` or `METIS_API_KEY` is set
- Feedback is included in `metis knowledge export` by default

Retrieve traces: `GET /v1/traces/{trace_id}` (redacted, auth required in production).
