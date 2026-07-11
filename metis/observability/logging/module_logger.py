"""Module call wrapper — logs every LLM provider invocation."""

from __future__ import annotations

import time
from typing import Optional

from metis.config import ModelSlot, RuntimeConfig
from metis.models.provider import LLMProvider, LLMResponse, Message
from metis.observability.config import ReliabilityConfig
from metis.observability.logging.tracer import (
    endpoint_host,
    log_module_call,
    new_span_id,
    set_span_id,
    summarize_content,
    summarize_messages,
)
from metis.observability.reliability.detector import classify_failure
from metis.observability.reliability.retry import RetryPolicy


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _provider_label(slot: ModelSlot) -> str:
    return slot.provider.value


class ObservedProvider(LLMProvider):
    """Wraps an LLM provider with structured logging, retries, and failure detection."""

    def __init__(
        self,
        inner: LLMProvider,
        slot: ModelSlot,
        *,
        module_role: Optional[str] = None,
        reliability: Optional[ReliabilityConfig] = None,
    ):
        self._inner = inner
        self._slot = slot
        self._role = module_role or slot.name
        self._retry = RetryPolicy(reliability)

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        span_id = new_span_id()
        set_span_id(span_id)
        request_summary = summarize_messages(messages)
        start = time.perf_counter()

        async def _call() -> LLMResponse:
            return await self._inner.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        try:
            resp = await self._retry.execute(
                _call,
                endpoint=self._slot.base_url,
                module_role=self._role,
                idempotent=True,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            usage = resp.usage or {}
            tokens_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0) or sum(
                _estimate_tokens(m.content) for m in messages
            )
            tokens_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0) or _estimate_tokens(
                resp.content
            )
            log_module_call(
                module_role=self._role,
                provider=_provider_label(self._slot),
                model=self._slot.model,
                endpoint=self._slot.base_url,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                status="ok",
                span_id=span_id,
                request_summary=request_summary,
                response_summary=summarize_content(resp.content),
            )
            return resp
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            record = classify_failure(exc, endpoint=endpoint_host(self._slot.base_url))
            log_module_call(
                module_role=self._role,
                provider=_provider_label(self._slot),
                model=self._slot.model,
                endpoint=self._slot.base_url,
                latency_ms=latency_ms,
                status="error",
                error_code=record.kind.value,
                span_id=span_id,
                request_summary=request_summary,
                extra={"error": record.message[:200]},
            )
            raise

    async def aclose(self) -> None:
        if hasattr(self._inner, "aclose"):
            await self._inner.aclose()


def observe_provider(
    provider: LLMProvider,
    slot: ModelSlot,
    config: Optional[RuntimeConfig] = None,
    *,
    module_role: Optional[str] = None,
) -> LLMProvider:
    """Wrap provider with observability if not already wrapped."""
    if isinstance(provider, ObservedProvider):
        return provider
    reliability = None
    if config and hasattr(config, "observability"):
        reliability = config.observability.reliability
    return ObservedProvider(provider, slot, module_role=module_role, reliability=reliability)
