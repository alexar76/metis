# База знаний и обучение в runtime

Metis v0.2: KnowledgeStore, ExperienceReplay, FailurePatterns, Feedback API.

```yaml
knowledge:
  enabled: true
  store_path: data/knowledge
  auto_replay_on_verify: true
```

```bash
metis knowledge export -o training_data.jsonl
```

Совет читает похожие TaskSpec перед синтезом. См. [KNOWLEDGE.md](../en/KNOWLEDGE.md).
