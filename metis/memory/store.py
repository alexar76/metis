"""Memory: working, episodic, and long-term vector store."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MemoryEntry:
    content: str
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorkingMemory:
    """Compressed session context + scratchpad."""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self.turns: list[tuple[str, str]] = []
        self.scratchpad: str = ""

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append((role, content))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def set_scratchpad(self, text: str) -> None:
        self.scratchpad = text

    def clear(self) -> None:
        """Reset session context — call at start of each stateless request."""
        self.turns.clear()
        self.scratchpad = ""

    def context(self) -> str:
        parts = []
        if self.scratchpad:
            parts.append(f"Scratchpad:\n{self.scratchpad}")
        for role, content in self.turns[-10:]:
            parts.append(f"{role}: {content[:500]}")
        return "\n".join(parts)


class EpisodicMemory:
    """What we tried and what failed in this session."""

    def __init__(self):
        self.episodes: list[dict] = []

    def record(self, action: str, outcome: str, success: bool) -> None:
        self.episodes.append({
            "action": action,
            "outcome": outcome,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def clear(self) -> None:
        """Reset per-request state — the shared brain reuses one instance across
        requests, so episodes must not bleed from one caller's run into another's."""
        self.episodes.clear()

    def failures(self) -> list[str]:
        return [e["outcome"] for e in self.episodes if not e["success"]]

    def summary(self) -> str:
        if not self.episodes:
            return ""
        lines = ["Previous attempts:"]
        for e in self.episodes[-5:]:
            status = "OK" if e["success"] else "FAIL"
            lines.append(f"- [{status}] {e['action']}: {e['outcome'][:200]}")
        return "\n".join(lines)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _tfidf_simple(query_tokens: set[str], doc_tokens: set[str], corpus_size: int, doc_freq: int) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    idf = math.log((corpus_size + 1) / (doc_freq + 1)) + 1
    return overlap * idf


class VectorMemory:
    """Lightweight long-term memory — JSON-backed, no external deps."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[MemoryEntry] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.entries = [MemoryEntry(**e) for e in data]

    def _save(self) -> None:
        payload = json.dumps([
            {"content": e.content, "metadata": e.metadata, "timestamp": e.timestamp}
            for e in self.entries
        ], ensure_ascii=False, indent=2)
        # Atomic write: tmp + os.replace prevents corruption on crash.
        import os as _os
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        _os.replace(tmp, self.path)

    def add(self, content: str, metadata: dict | None = None) -> None:
        self.entries.append(MemoryEntry(content=content, metadata=metadata or {}))
        self._save()

    def search(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        if not self.entries:
            return []
        q_tokens = _tokenize(query)
        scored = []
        for entry in self.entries:
            d_tokens = _tokenize(entry.content)
            df = sum(1 for e in self.entries if _tokenize(e.content) & d_tokens)
            score = _tfidf_simple(q_tokens, d_tokens, len(self.entries), df)
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for s, e in scored[:top_k] if s > 0]

    def context_for(self, query: str, top_k: int = 5) -> str:
        hits = self.search(query, top_k)
        if not hits:
            return ""
        return "Relevant memory:\n" + "\n".join(f"- {h.content[:300]}" for h in hits)
