# Knowledge & Runtime Learning

Metis v0.2 adds shared knowledge storage and runtime learning — **not** online weight fine-tuning. Verified experiences are stored for council context and offline SFT export.

## Components

| Component | Purpose |
|-----------|---------|
| **KnowledgeStore** | SQLite + TF-IDF similarity (pgvector when `database_url` set) |
| **ExperienceReplay** | Auto-save traces where `verify_pass=true` |
| **FailurePatterns** | Track recurring failure types per query category |
| **Feedback API** | `POST /v1/feedback {trace_id, rating, comment}` |

## Configuration

```yaml
knowledge:
  enabled: true
  store_path: data/knowledge
  auto_replay_on_verify: true
  similarity_top_k: 3
  min_similarity: 0.1
```

## Council integration

Before synthesizing a `TaskSpec`, the Understanding Council reads similar verified past tasks from the knowledge store and injects them as context.

## Experience replay

When verification passes (`verify_score >= 0.7`), the run is saved with TaskSpec, query, answer, and trace metadata.

## Export for offline SFT

```bash
metis knowledge export -o training_data.jsonl
metis knowledge export --no-feedback  # experiences only
```

Output is JSONL suitable for supervised fine-tuning pipelines.

## Feedback

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Authorization: Bearer $METIS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"trace_id": "abc123", "rating": 5, "comment": "accurate"}'
```

Auth is required when `METIS_PRODUCTION=1` or `METIS_API_KEY` is set.

## Failure patterns

Failures are categorized (coding, reasoning, factual) and tracked by `FailureKind`. Hints are injected into council context to avoid repeated mistakes.
