# Knowledge & Runtime Learning

Shared knowledge store, experience replay on verified answers, failure pattern tracking, and SFT export.

## CLI

```bash
metis knowledge export -o training_data.jsonl
```

## API

`POST /v1/feedback` with `{trace_id, rating, comment}` — auth required in production.

See [docs/en/KNOWLEDGE.md](../docs/en/KNOWLEDGE.md).
