"""Auto-save verified traces for runtime learning."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from metis.knowledge.store import KnowledgeEntry, KnowledgeStore
from metis.schemas.task_spec import TaskSpec


class ExperienceReplay:
    """Persist successful runs (verify_pass=true) for council context and SFT export."""

    def __init__(self, store: KnowledgeStore):
        self.store = store

    def maybe_save(
        self,
        *,
        query: str,
        answer: str,
        task_spec: Optional[TaskSpec],
        verify_pass: bool,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not verify_pass or not task_spec:
            return None
        entry_id = trace_id or uuid.uuid4().hex
        category = _categorize_query(query)
        entry = KnowledgeEntry(
            id=entry_id,
            task_spec_json=task_spec.model_dump_json(),
            query=query,
            answer=answer,
            category=category,
            metadata=metadata or {},
            verify_pass=True,
        )
        self.store.add(entry)
        return entry_id


def _categorize_query(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ("code", "python", "function", "implement")):
        return "coding"
    if any(w in q for w in ("explain", "why", "how")):
        return "reasoning"
    if any(w in q for w in ("what is", "who", "when", "where")):
        return "factual"
    return "general"
