"""Track recurring failure patterns per query category."""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from metis.knowledge.experience import _categorize_query
from metis.observability.reliability.detector import FailureKind


class FailurePatterns:
    """Aggregate failure kinds by query category for adaptive routing hints."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path / "failure_patterns.json"
        self._data: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            raw = json.loads(self._file.read_text())
            for cat, kinds in raw.items():
                self._data[cat] = defaultdict(int, kinds)

    def _save(self) -> None:
        serializable = {k: dict(v) for k, v in self._data.items()}
        self._file.write_text(json.dumps(serializable, indent=2))

    def record(self, query: str, kind: FailureKind) -> None:
        cat = _categorize_query(query)
        with self._lock:
            self._data[cat][kind.value] += 1
            self._save()

    def top_failures(self, category: str, n: int = 3) -> List[tuple[str, int]]:
        kinds = self._data.get(category, {})
        ranked = sorted(kinds.items(), key=lambda x: x[1], reverse=True)
        return ranked[:n]

    def summary(self) -> Dict[str, Dict[str, int]]:
        return {k: dict(v) for k, v in self._data.items()}

    def hint_for_query(self, query: str) -> str:
        cat = _categorize_query(query)
        top = self.top_failures(cat)
        if not top:
            return ""
        parts = [f"{k}({v})" for k, v in top]
        return f"Known failure patterns for {cat}: {', '.join(parts)}"
