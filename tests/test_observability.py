"""Observability system tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from metis.config import ModelSlot, ProviderKind, RuntimeConfig
from metis.models.provider import LLMResponse, Message
from metis.observability.config import LogContentMode, ReliabilityConfig
from metis.observability.logging.audit import audit_event, configure_audit
from metis.observability.logging.module_logger import ObservedProvider
from metis.observability.logging.tracer import (
    clear_trace,
    get_trace_id,
    init_logging,
    log_module_call,
    set_trace_id,
    start_trace,
    summarize_content,
)
from metis.observability.reliability.circuit_breaker import get_breaker, reset_breakers
from metis.observability.reliability.detector import FailureKind, classify_failure
from metis.observability.reliability.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _reset_observability():
    reset_breakers()
    clear_trace()
    yield
    reset_breakers()
    clear_trace()


class _FakeProvider:
    def __init__(self, responses=None, exc=None):
        self._responses = list(responses or ["ok"])
        self._exc = exc
        self.calls = 0

    async def complete(self, messages, *, temperature=None, max_tokens=None):
        self.calls += 1
        if self._exc:
            raise self._exc
        content = self._responses.pop(0) if self._responses else "ok"
        return LLMResponse(content=content, model="test", usage={"prompt_tokens": 10, "completion_tokens": 5})


def test_trace_id_propagation():
    ctx = start_trace(metadata={"test": True})
    assert get_trace_id() == ctx.trace_id
    set_trace_id(ctx.trace_id)
    child_tid = get_trace_id()
    assert child_tid == ctx.trace_id
    clear_trace()
    assert get_trace_id() is None


def test_redacted_logging_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_LOG_CONTENT", "redacted")
    log_file = tmp_path / "metis.jsonl"
    monkeypatch.setenv("METIS_LOG_FILE", str(log_file))

    import logging
    logging.getLogger("metis").handlers.clear()
    import metis.observability.logging.tracer as tracer_mod
    tracer_mod._logger = None

    init_logging()
    secret = "api_key=sk-supersecret12345 Bearer abc.def.ghi"
    summary = summarize_content(f"prompt with {secret}")
    assert "sk-supersecret" not in json.dumps(summary)
    assert "sha256_prefix" in summary
    assert summary["length"] > 0

    set_trace_id("test-trace-001")
    log_module_call(
        "judge",
        module_role="judge",
        provider="mock",
        model="test",
        endpoint="http://localhost:11434/v1",
        latency_ms=12.5,
        tokens_in=10,
        tokens_out=5,
        status="ok",
        request_summary=summarize_content(secret),
    )
    if log_file.exists():
        line = log_file.read_text()
        assert "sk-supersecret" not in line
        assert "test-trace-001" in line


def test_retry_on_timeout():
    policy = ReliabilityConfig(max_retries=2, base_delay_ms=1, max_delay_ms=10)
    provider = _FakeProvider(exc=httpx.TimeoutException("timed out"))
    slot = ModelSlot(name="judge", provider=ProviderKind.MOCK, model="m", base_url="http://localhost/v1")
    observed = ObservedProvider(provider, slot, reliability=policy)

    async def _run():
        with pytest.raises(httpx.TimeoutException):
            await observed.complete([Message("user", "hi")])

    import asyncio
    asyncio.run(_run())
    assert provider.calls == 3  # initial + 2 retries


def test_circuit_breaker_opens():
    from metis.observability.config import CircuitBreakerConfig

    cfg = CircuitBreakerConfig(enabled=True, failure_threshold=3, recovery_seconds=60)
    breaker = get_breaker("localhost:11434", cfg)
    for _ in range(3):
        breaker.record_failure(FailureKind.NETWORK)
    with pytest.raises(RuntimeError, match="Circuit breaker"):
        breaker.before_call()


def test_failure_classification():
    record = classify_failure(httpx.TimeoutException("timeout"))
    assert record.kind == FailureKind.TIMEOUT
    assert record.retryable is True

    resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    record = classify_failure(httpx.HTTPStatusError("rate", request=resp.request, response=resp))
    assert record.kind == FailureKind.RATE_LIMIT

    record = classify_failure(ValueError("json parse error"))
    assert record.kind == FailureKind.PARSE_ERROR
    assert record.retryable is False

    record = classify_failure(RuntimeError("injection detected in input"))
    assert record.kind == FailureKind.INJECTION_BLOCKED


def test_audit_log_no_prompt_content(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    configure_audit(path=str(audit_path), hash_chain=True)
    set_trace_id("audit-trace-1")
    audit_event(
        "auth_failure",
        severity="warning",
        details={
            "prompt": "secret user prompt",
            "api_key": "sk-live",
            "reason": "invalid token",
            "endpoint": "localhost",
        },
    )
    line = audit_path.read_text().strip()
    data = json.loads(line)
    assert "secret user prompt" not in line
    assert "sk-live" not in line
    assert data["details"]["reason"] == "invalid token"
    assert "hash" in data
    assert "prev_hash" in data


@pytest.mark.asyncio
async def test_observed_provider_logs_success():
    inner = _FakeProvider(responses=["hello"])
    slot = ModelSlot(name="router", provider=ProviderKind.MOCK, model="m", base_url="http://localhost:11434/v1")
    observed = ObservedProvider(inner, slot, reliability=ReliabilityConfig(max_retries=0))
    set_trace_id("span-test")
    resp = await observed.complete([Message("user", "test")])
    assert resp.content == "hello"
    assert inner.calls == 1
