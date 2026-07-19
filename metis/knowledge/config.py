"""Knowledge layer configuration."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeConfig(BaseModel):
    enabled: bool = True
    store_path: str = "data/knowledge"
    database_url: Optional[str] = None  # pgvector when set
    auto_replay_on_verify: bool = True
    similarity_top_k: int = 3
    min_similarity: float = 0.1
    export_include_feedback: bool = True
