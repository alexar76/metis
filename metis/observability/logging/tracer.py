"""Structured JSON logging, trace context, and per-module spans."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import uuid
import warnings
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from metis.observability.config import LogContentMode, ObservabilityConfig

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
_spans: ContextVar[List[Dict[str, Any]]] = ContextVar("spans", default=[])
_config: Optional[ObservabilityConfig] = None
_logger: Optional[logging.Logger] = None
_log_file_lock = threading.Lock()

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+", re.I),
]


@dataclass
class TraceContext:
    trace_id: str
    spans: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "spans": self.spans,
            "events": self.events,
            "metadata": self.metadata,
        }


def _content_mode() -> LogContentMode:
    env = os.environ.get("METIS_LOG_CONTENT", "").lower()
    if env in ("full", "hash", "redacted"):
        return LogContentMode(env)
    if _config:
        return _config.log_content
    return LogContentMode.REDACTED


def _scrub_secrets(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def _stringify_content(content: Any) -> str:
    """Flatten message content to a compact string for logging/hashing.

    Multimodal content is a list of OpenAI parts (text + image_url). NEVER log or
    hash the raw base64 image payload — collapse each image to a short marker.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for p in content:
            if isinstance(p, dict):
                t = p.get("type")
                if t == "text":
                    bits.append(str(p.get("text", "")))
                elif t == "image_url":
                    bits.append("[image]")
                else:
                    bits.append(f"[{t}]" if t else "[part]")
            else:
                bits.append(str(p))
        return " ".join(bits)
    return str(content)


def summarize_content(text: Any, mode: Optional[LogContentMode] = None) -> Dict[str, Any]:
    """Summarize content — redacted by default (length + sha256 prefix only)."""
    mode = mode or _content_mode()
    if not isinstance(text, str):
        text = _stringify_content(text)
    if not text:
        return {"length": 0}

    if mode == LogContentMode.FULL:
        if os.environ.get("METIS_PRODUCTION", "").lower() in ("1", "true", "yes"):
            warnings.warn("METIS_LOG_CONTENT=full in production", stacklevel=2)
        return {"length": len(text), "content": _scrub_secrets(text)}

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    summary: Dict[str, Any] = {"length": len(text), "sha256_prefix": digest[:16]}
    if mode == LogContentMode.HASH:
        summary["sha256"] = digest
    return summary


def _sanitize_content(text: str) -> str:
    """Legacy string sanitizer for backward compatibility."""
    mode = _content_mode()
    if not text:
        return text
    if mode == LogContentMode.FULL:
        return _scrub_secrets(text)
    if mode == LogContentMode.HASH:
        return f"sha256:{hashlib.sha256(text.encode()).hexdigest()[:16]}"
    return f"[redacted len={len(text)}]"


def summarize_messages(messages: list) -> Dict[str, Any]:
    parts = []
    total_len = 0
    for m in messages:
        content = _stringify_content(getattr(m, "content", str(m)))
        total_len += len(content)
        parts.append(summarize_content(content))
    return {"message_count": len(messages), "total_length": total_len, "messages": parts}


def endpoint_host(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return "unknown"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        tid = get_trace_id()
        if tid:
            payload["trace_id"] = tid
        sid = get_span_id()
        if sid:
            payload["span_id"] = sid
        for key in (
            "module", "module_role", "span_id", "duration_ms", "latency_ms",
            "event", "extra", "provider", "model", "endpoint", "status",
            "error_code", "tokens_in", "tokens_out",
        ):
            if hasattr(record, key):
                val = getattr(record, key)
                if val is not None:
                    payload[key] = val
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _write_log_line(line: str) -> None:
    path = (_config.log_file if _config else None) or os.environ.get("METIS_LOG_FILE")
    if path:
        with _log_file_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


class _JsonStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self.stream.write(line + self.terminator)
            self.flush()
            _write_log_line(line)
        except Exception:
            self.handleError(record)


def init_logging(config: Optional[ObservabilityConfig] = None) -> None:
    global _config, _logger
    if _logger is not None:
        return
    _config = config or ObservabilityConfig()
    level_name = os.environ.get("METIS_LOG_LEVEL", _config.log_level)
    level = getattr(logging, level_name.upper(), logging.INFO)
    log_format = os.environ.get("METIS_LOG_FORMAT", _config.log_format)
    log_file = os.environ.get("METIS_LOG_FILE") or _config.log_file

    root = logging.getLogger("metis")
    root.handlers.clear()
    root.setLevel(level)
    root.propagate = False

    if log_file:
        from pathlib import Path
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_file)
    else:
        handler = _JsonStreamHandler(sys.stdout)

    if log_format.lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root.addHandler(handler)
    _logger = root

    if _content_mode() == LogContentMode.FULL:
        warnings.warn("METIS_LOG_CONTENT=full — prompts may be logged", stacklevel=1)


def get_trace_id() -> Optional[str]:
    return _trace_id.get()


def get_span_id() -> Optional[str]:
    return _span_id.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id)


def set_span_id(span_id: str) -> None:
    _span_id.set(span_id)


def new_span_id() -> str:
    return uuid.uuid4().hex[:12]


def start_trace(metadata: Optional[Dict[str, Any]] = None) -> TraceContext:
    tid = str(uuid.uuid4())
    set_trace_id(tid)
    set_span_id(new_span_id())
    _spans.set([])
    ctx = TraceContext(trace_id=tid, metadata=metadata or {})
    if _logger is None:
        init_logging()
    _log_structured("trace_start", {"event": "trace_start", "trace_id": tid})
    return ctx


def clear_trace() -> None:
    _trace_id.set(None)
    _span_id.set(None)
    _spans.set([])


def _log_structured(message: str, fields: Dict[str, Any], *, level: int = logging.INFO) -> None:
    if _logger is None:
        init_logging()
    record = _logger.makeRecord("metis.trace", level, "(tracer)", 0, message, (), None)
    for key, val in fields.items():
        setattr(record, key, val)
    _logger.handle(record)


def log_module_call(
    module_or_role: Optional[str] = None,
    *,
    duration_ms: Optional[float] = None,
    latency_ms: Optional[float] = None,
    success: Optional[bool] = None,
    error: Optional[str] = None,
    prompt: Optional[str] = None,
    response: Optional[str] = None,
    module_role: Optional[str] = None,
    provider: str = "",
    model: str = "",
    endpoint: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    status: Optional[str] = None,
    error_code: Optional[str] = None,
    span_id: Optional[str] = None,
    request_summary: Optional[Dict[str, Any]] = None,
    response_summary: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if _logger is None:
        init_logging()

    role = module_role or module_or_role or "unknown"
    ms = latency_ms if latency_ms is not None else (duration_ms or 0.0)
    st = status or ("ok" if (success is None or success) else "error")
    sid = span_id or new_span_id()
    set_span_id(sid)

    span: Dict[str, Any] = {
        "span_id": sid,
        "module_role": role,
        "latency_ms": round(ms, 2),
        "status": st,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if provider:
        span["provider"] = provider
    if model:
        span["model"] = model
    if endpoint:
        span["endpoint"] = endpoint_host(endpoint)
    if tokens_in:
        span["tokens_in"] = tokens_in
    if tokens_out:
        span["tokens_out"] = tokens_out
    if error_code:
        span["error_code"] = error_code
    if error:
        span["error"] = error[:200]
    if request_summary:
        span["request"] = request_summary
    elif prompt is not None:
        span["request"] = summarize_content(prompt)
    if response_summary:
        span["response"] = response_summary
    elif response:
        span["response"] = summarize_content(response)
    if extra:
        span.update(extra)

    spans = list(_spans.get())
    spans.append(span)
    _spans.set(spans)

    _log_structured(
        f"module_call {role} {st}",
        {
            "event": "module_call",
            "module_role": role,
            "provider": provider,
            "model": model,
            "endpoint": endpoint_host(endpoint) if endpoint else "",
            "latency_ms": ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "status": st,
            "error_code": error_code or "",
            "span_id": sid,
        },
        level=logging.INFO if st == "ok" else logging.WARNING,
    )


def get_current_spans() -> List[Dict[str, Any]]:
    return list(_spans.get())


def build_trace_record(
    ctx: TraceContext,
    *,
    query: str = "",
    answer: str = "",
    status: str = "",
    route: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx.spans = get_current_spans()
    record = ctx.to_dict()
    record.update({
        "query": summarize_content(query),
        "answer": summarize_content(answer),
        "status": status,
        "route": route,
        "metadata": {**(ctx.metadata), **(metadata or {})},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return record
