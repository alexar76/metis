"""Tracked provider wrapper for usage metering."""

from __future__ import annotations

import time

from metis.config import ModelSlot
from metis.economy.meter import get_current_meter
from metis.models.provider import LLMProvider, LLMResponse, Message


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _provider_label(slot: ModelSlot) -> str:
    url = slot.base_url.lower()
    if "anthropic" in url:
        return "anthropic"
    if "deepseek" in url:
        return "deepseek"
    if "openai" in url:
        return "openai"
    if "localhost" in url or "11434" in url:
        return "local"
    return slot.provider.value


class TrackedProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, slot: ModelSlot):
        self._inner = inner
        self._slot = slot

    async def complete(self, messages: list[Message], *, temperature: float | None = None, max_tokens: int | None = None) -> LLMResponse:
        meter = get_current_meter()
        start = time.perf_counter()
        resp = await self._inner.complete(messages, temperature=temperature, max_tokens=max_tokens)
        latency_ms = (time.perf_counter() - start) * 1000
        if meter:
            u = resp.usage or {}
            ti = int(u.get("prompt_tokens") or u.get("input_tokens") or 0) or sum(_estimate_tokens(m.content) for m in messages)
            to = int(u.get("completion_tokens") or u.get("output_tokens") or 0) or _estimate_tokens(resp.content)
            meter.record_llm(
                model=self._slot.model,
                provider=_provider_label(self._slot),
                role=self._slot.name,
                tokens_in=ti,
                tokens_out=to,
                latency_ms=latency_ms,
                node_id=self._slot.node_id,
            )
        return resp

    async def aclose(self) -> None:
        if hasattr(self._inner, "aclose"):
            await self._inner.aclose()
