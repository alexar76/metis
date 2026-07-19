"""Persist and query trace records."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class TraceStore:
    """JSONL-backed trace storage."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._file = self.directory / "traces.jsonl"

    def save(self, record: Dict[str, Any]) -> None:
        record.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        with self._file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get(self, trace_id: str) -> Optional[Dict[str, Any]]:
        if not self._file.exists():
            return None
        for line in self._file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("trace_id") == trace_id:
                return rec
        return None

    def tail(self, n: int = 20, *, follow: bool = False) -> List[Dict[str, Any]]:
        if not self._file.exists():
            return []
        lines = [ln for ln in self._file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        records = []
        for line in lines[-n:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return records

    def stats(self) -> Dict[str, Any]:
        if not self._file.exists():
            return {
                "total": 0, "by_status": {}, "by_route": {},
                "by_module": {}, "by_endpoint": {}, "failures_by_kind": {},
                "failure_rate_pct": 0.0,
            }
        by_status: Dict[str, int] = {}
        by_route: Dict[str, int] = {}
        by_module: Counter = Counter()
        by_endpoint: Counter = Counter()
        failures_by_kind: Counter = Counter()
        module_calls = 0
        module_errors = 0
        total = 0
        for line in self._file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            st = rec.get("status", "unknown")
            rt = rec.get("route", "unknown")
            by_status[st] = by_status.get(st, 0) + 1
            by_route[rt] = by_route.get(rt, 0) + 1
            for span in rec.get("spans", []):
                module_calls += 1
                role = span.get("module_role", span.get("module", "unknown"))
                ep = span.get("endpoint", "unknown")
                by_module[role] += 1
                by_endpoint[ep] += 1
                if span.get("status") == "error":
                    module_errors += 1
                    failures_by_kind[span.get("error_code", "unknown")] += 1
        failure_rate = (module_errors / module_calls * 100) if module_calls else 0.0
        return {
            "total": total,
            "by_status": by_status,
            "by_route": by_route,
            "module_calls": module_calls,
            "module_errors": module_errors,
            "failure_rate_pct": round(failure_rate, 2),
            "by_module": dict(by_module),
            "by_endpoint": dict(by_endpoint),
            "failures_by_kind": dict(failures_by_kind),
        }
