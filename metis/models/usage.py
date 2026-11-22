"""A persistent journal for individual upstream model dispatches."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

logger = logging.getLogger(__name__)

MCPToolRef = tuple[str, str]


def sent_mcp(messages) -> list[dict]:
    servers: dict[str, dict] = {}
    for message in messages:
        for key, refs in (("tools", message.mcp_tools), ("result_tools", message.mcp_results)):
            for server, name in refs:
                row = servers.setdefault(server, {"server": server, "tools": [], "result_tools": []})
                if name not in row[key]:
                    row[key].append(name)
    return list(servers.values())


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _fields(body, host, anthropic):
    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    read = _count(details.get("cached_tokens"))
    if read is None:
        read = _count(usage.get("prompt_cache_hit_tokens"))
    write = _count(details.get("cache_write_tokens"))
    misses = _count(usage.get("prompt_cache_miss_tokens"))
    input_tokens = _count(usage.get("prompt_tokens"))
    output_tokens = _count(usage.get("completion_tokens"))
    if anthropic:
        read = _count(usage.get("cache_read_input_tokens"))
        write = _count(usage.get("cache_creation_input_tokens"))
        misses = _count(usage.get("input_tokens"))
        input_tokens = sum(n or 0 for n in (misses, read, write)) if misses is not None else None
        output_tokens = _count(usage.get("output_tokens"))
    cost = usage.get("cost") if host == "openrouter.ai" else None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": read,
        "cache_write_input_tokens": write,
        "cache_miss_input_tokens": misses,
        "provider_cost_usd": cost if type(cost) in (int, float) and 0 <= cost <= 1e100 else None,
    }


@contextmanager
def model_usage(slot, url, mcp_servers, *, anthropic=False):
    started = monotonic()
    host = urlsplit(url).hostname
    stamp = datetime.now(UTC).isoformat()
    observed = {}
    outcome = "error"
    try:
        yield observed
        body = observed.get("body")
        if isinstance(body, dict) and not body.get("error"):
            outcome = "ok"
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        response = observed.get("response")
        body = observed.get("body")
        if not isinstance(body, dict):
            body = {}
        headers = getattr(response, "headers", {})
        row = {
            "schema_version": 1,
            "call_id": str(uuid4()),
            "timestamp": stamp,
            "service": "metis",
            "provider": slot.provider.value,
            "provider_host": host,
            "model": slot.model,
            "model_role": slot.name,
            "provider_model": body.get("model") if isinstance(body.get("model"), str) else None,
            "provider_generation_id": body.get("id") if isinstance(body.get("id"), str) else None,
            "provider_request_id": headers.get("request-id") or headers.get("x-request-id"),
            "http_status": getattr(response, "status_code", None),
            "outcome": outcome,
            "latency_ms": round((monotonic() - started) * 1000, 2),
            "mcp_servers": mcp_servers,
            **_fields(body, host, anthropic),
        }
        try:
            path = Path(os.environ.get("METIS_MODEL_USAGE_LOG", "data/model_usage.jsonl"))
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = (json.dumps(row, separators=(",", ":")) + "\n").encode()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, encoded)
            finally:
                os.close(fd)
        except (OSError, ValueError):
            logger.warning("Could not append Metis model usage")
