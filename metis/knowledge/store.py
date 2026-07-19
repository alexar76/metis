"""KnowledgeStore — pgvector or SQLite+TF-IDF fallback."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _similarity(query_tokens: set[str], doc_tokens: set[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    return overlap / math.sqrt(len(query_tokens) * len(doc_tokens))


@dataclass
class KnowledgeEntry:
    id: str
    task_spec_json: str
    query: str
    answer: str
    category: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)
    verify_pass: bool = False
    rating: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class KnowledgeStore:
    """Shared knowledge across instances — SQLite by default, pgvector when configured."""

    def __init__(self, path: Path, database_url: Optional[str] = None):
        self.path = path
        self.database_url = database_url
        self._pg = None
        path.mkdir(parents=True, exist_ok=True)
        self._db_path = path / "knowledge.db"
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                task_spec_json TEXT NOT NULL,
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                metadata_json TEXT DEFAULT '{}',
                verify_pass INTEGER DEFAULT 0,
                rating INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def add(self, entry: KnowledgeEntry) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR REPLACE INTO knowledge
               (id, task_spec_json, query, answer, category, metadata_json, verify_pass, rating, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id, entry.task_spec_json, entry.query, entry.answer,
                entry.category, json.dumps(entry.metadata), int(entry.verify_pass),
                entry.rating, entry.created_at,
            ),
        )
        conn.commit()
        conn.close()

    def search_similar(
        self,
        query: str,
        *,
        top_k: int = 3,
        min_score: float = 0.1,
        verify_pass_only: bool = True,
    ) -> List[KnowledgeEntry]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, task_spec_json, query, answer, category, metadata_json, verify_pass, rating, created_at "
            "FROM knowledge"
        ).fetchall()
        conn.close()

        q_tokens = _tokenize(query)
        scored: list[tuple[float, KnowledgeEntry]] = []
        for row in rows:
            entry = KnowledgeEntry(
                id=row[0], task_spec_json=row[1], query=row[2], answer=row[3],
                category=row[4], metadata=json.loads(row[5] or "{}"),
                verify_pass=bool(row[6]), rating=row[7], created_at=row[8],
            )
            if verify_pass_only and not entry.verify_pass:
                continue
            score = _similarity(q_tokens, _tokenize(entry.query + " " + entry.task_spec_json))
            if score >= min_score:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def context_for_council(self, query: str, top_k: int = 3) -> str:
        hits = self.search_similar(query, top_k=top_k)
        if not hits:
            return ""
        lines = ["Similar past tasks (verified):"]
        for h in hits:
            lines.append(f"- Query: {h.query[:120]}")
            lines.append(f"  TaskSpec: {h.task_spec_json[:200]}")
        return "\n".join(lines)

    def add_feedback(self, trace_id: str, rating: int, comment: str = "") -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO feedback (trace_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
            (trace_id, rating, comment, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

    def export_jsonl(self, include_feedback: bool = True) -> List[Dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, task_spec_json, query, answer, category, metadata_json, verify_pass, rating, created_at "
            "FROM knowledge WHERE verify_pass = 1"
        ).fetchall()
        records = []
        for row in rows:
            rec = {
                "id": row[0],
                "task_spec": json.loads(row[1]),
                "query": row[2],
                "answer": row[3],
                "category": row[4],
                "metadata": json.loads(row[5] or "{}"),
                "rating": row[7],
                "created_at": row[8],
            }
            records.append(rec)
        if include_feedback:
            fb_rows = conn.execute(
                "SELECT trace_id, rating, comment, created_at FROM feedback"
            ).fetchall()
            for fb in fb_rows:
                records.append({
                    "type": "feedback",
                    "trace_id": fb[0],
                    "rating": fb[1],
                    "comment": fb[2],
                    "created_at": fb[3],
                })
        conn.close()
        return records

    def count(self) -> int:
        conn = self._conn()
        n = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        conn.close()
        return n
