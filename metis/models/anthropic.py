"""Native Anthropic Messages API provider."""

from __future__ import annotations

from typing import Optional

import httpx

from metis.config import ModelSlot
from metis.models.provider import LLMProvider, LLMResponse, Message


class AnthropicProvider(LLMProvider):
    """Anthropic /v1/messages adapter."""

    def __init__(self, slot: ModelSlot):
        self.slot = slot
        base = slot.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = base + "/v1" if "/v1" not in base else base
        self._url = base.replace("/v1", "") + "/v1/messages" if "/messages" not in base else base
        if not self._url.endswith("/messages"):
            self._url = slot.base_url.rstrip("/")
            if not self._url.endswith("/messages"):
                self._url = "https://api.anthropic.com/v1/messages"
        self._client = httpx.AsyncClient(
            headers={
                "x-api-key": slot.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        system_parts = [m.content for m in messages if m.role == "system"]
        user_messages = [
            {"role": "user" if m.role == "user" else "assistant", "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        payload = {
            "model": self.slot.model,
            "max_tokens": max_tokens or self.slot.max_tokens,
            "messages": user_messages,
            "temperature": temperature if temperature is not None else self.slot.temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        r = await self._client.post(self._url, json=payload)
        r.raise_for_status()
        data = r.json()
        content_blocks = data.get("content", [])
        text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")
        usage = data.get("usage", {})
        return LLMResponse(
            content=text,
            model=data.get("model", self.slot.model),
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            raw=data,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
