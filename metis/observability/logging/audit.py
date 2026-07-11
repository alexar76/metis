"""Tamper-evident audit log for security-sensitive events — no PII or prompts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from metis.observability.logging.tracer import get_trace_id

_prev_hash: str = "genesis"
_audit_path: Optional[Path] = None
_hash_chain: bool = False
_audit_logger: Optional[logging.Logger] = None

_FORBIDDEN_KEYS = frozenset({
    "prompt", "content", "api_key", "secret", "password", "token",
    "authorization", "user_query", "answer", "messages", "query",
})


def configure_audit(*, path: Optional[str] = None, hash_chain: bool = False) -> None:
    global _audit_path, _hash_chain, _prev_hash
    _hash_chain = hash_chain
    path = path or os.environ.get("METIS_AUDIT_LOG_FILE") or os.environ.get("METIS_AUDIT_LOG_PATH")
    if path:
        _audit_path = Path(path)
        _audit_path.parent.mkdir(parents=True, exist_ok=True)
        if _hash_chain and _audit_path.exists():
            for line in _audit_path.read_text().splitlines():
                if line.strip():
                    try:
                        _prev_hash = json.loads(line).get("hash", _prev_hash)
                    except json.JSONDecodeError:
                        pass


def _sanitize_details(details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not details:
        return {}
    safe: Dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in _FORBIDDEN_KEYS:
            continue
        if isinstance(value, str) and len(value) > 200:
            safe[key] = {"length": len(value)}
        elif isinstance(value, dict):
            safe[key] = _sanitize_details(value)
        else:
            safe[key] = value
    return safe


def _get_audit_logger() -> logging.Logger:
    global _audit_logger
    if _audit_logger:
        return _audit_logger
    _audit_logger = logging.getLogger("metis.observability.audit")
    _audit_logger.handlers.clear()
    _audit_logger.propagate = False
    _audit_logger.setLevel(logging.INFO)
    if _audit_path:
        fh = logging.FileHandler(_audit_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        _audit_logger.addHandler(fh)
    return _audit_logger


def audit_event(
    event_type: str,
    *,
    severity: str = "info",
    source: str = "metis",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    global _prev_hash
    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "severity": severity,
        "source": source,
        "trace_id": get_trace_id(),
        "details": _sanitize_details(details),
    }
    if _hash_chain:
        payload = json.dumps({k: v for k, v in entry.items() if k != "hash"}, sort_keys=True, ensure_ascii=False)
        entry["prev_hash"] = _prev_hash
        entry["hash"] = hashlib.sha256(f"{_prev_hash}:{payload}".encode()).hexdigest()
        _prev_hash = entry["hash"]

    line = json.dumps(entry, ensure_ascii=False, default=str)
    if _audit_path:
        with _audit_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    else:
        logger = _get_audit_logger()
        if severity == "critical":
            logger.critical(line)
        elif severity == "warning":
            logger.warning(line)
        else:
            logger.info(line)
