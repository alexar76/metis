"""Universal LLM provider — production backends only."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional

import httpx

from metis.config import ModelSlot, ProviderKind, RuntimeConfig

# Model-name fragments that indicate native vision (multimodal input) support.
_VISION_HINTS = (
    "gpt-4o", "gpt-4.1", "gpt-4-vision", "gpt-4-turbo", "o1", "o3", "o4",
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    "gemini", "llava", "bakllava", "llama-3.2-vision", "llama3.2-vision",
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "pixtral", "moondream", "minicpm-v",
    "phi-3-vision", "phi-3.5-vision", "internvl", "cogvlm", "-vl", "vision",
)


def model_supports_vision(slot: ModelSlot) -> bool:
    """True if the slot can accept image input (explicit override or name heuristic)."""
    if slot.supports_vision is not None:
        return bool(slot.supports_vision)
    name = (slot.model or "").lower()
    return any(h in name for h in _VISION_HINTS)


@dataclass
class Message:
    role: str
    content: Any  # str for text, or a list of OpenAI content parts for multimodal


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        ...

    async def complete_text(self, system: str, user: str, **kwargs) -> str:
        resp = await self.complete(
            [Message("system", system), Message("user", user)],
            **kwargs,
        )
        return resp.content

    async def complete_multimodal(
        self, system: str, user_text: str, image_urls: List[str], **kwargs
    ) -> str:
        """Vision completion — sends text + images in OpenAI content-part format.

        Works natively for OpenAI-compatible / Ollama vision backends (the list
        content is passed straight through). Providers with a different wire
        format may override this.
        """
        parts: List[dict] = [{"type": "text", "text": user_text}]
        for url in image_urls:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        resp = await self.complete(
            [Message("system", system), Message("user", parts)], **kwargs
        )
        return resp.content


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible: vLLM, Ollama, OpenAI, DeepSeek, LiteLLM."""

    # Reasoning models (deepseek-v4-*, o-series, …) spend tokens on a hidden
    # chain-of-thought BEFORE emitting the answer. max_tokens caps CoT+answer
    # together, so a tight budget can starve the answer and return empty content.
    # Once we detect such a model we keep its budget at/above this floor and, on a
    # length-truncated empty answer, retry with a larger budget — so `content` is
    # reliably clean and complete rather than empty or raw CoT.
    _REASONING_TOKEN_FLOOR = 8000
    _REASONING_RETRY_CAP = 32000

    def __init__(self, slot: ModelSlot):
        self.slot = slot
        self._reasoning_model = False  # flipped on when a response carries reasoning_content
        headers = {"Authorization": f"Bearer {slot.api_key}"}
        # Optional per-slot headers (e.g. OpenRouter's HTTP-Referer / X-Title,
        # which improve free-tier priority). String-cast defensively.
        for k, v in (getattr(slot, "extra_headers", None) or {}).items():
            headers[str(k)] = str(v)
        self._client = httpx.AsyncClient(
            base_url=slot.base_url.rstrip("/"),
            headers=headers,
            timeout=120.0,
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        requested = max_tokens or self.slot.max_tokens
        # Give a known reasoning model enough headroom up front so the answer is not
        # starved by the hidden CoT (avoids the truncation retry on the common path).
        if self._reasoning_model:
            requested = max(requested, self._REASONING_TOKEN_FLOOR)
        payload = {
            "model": self.slot.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature if temperature is not None else self.slot.temperature,
            "max_tokens": requested,
        }
        data = await self._post(payload)
        choice = data["choices"][0]
        msg = choice["message"]
        if msg.get("reasoning_content"):
            self._reasoning_model = True  # remember for subsequent calls on this slot

        content = (msg.get("content") or "").strip()
        # Reasoning model + length-truncated empty answer: the CoT ate the whole
        # budget before the answer. Retry once with a much larger budget so we get
        # clean, complete content — not an empty string and not raw chain-of-thought.
        if not content and msg.get("reasoning_content") and choice.get("finish_reason") == "length":
            payload["max_tokens"] = min(max(requested * 4, self._REASONING_TOKEN_FLOOR), self._REASONING_RETRY_CAP)
            data = await self._post(payload)
            choice = data["choices"][0]
            msg = choice["message"]
            content = (msg.get("content") or "").strip()

        # Last resort — never hand back a blank answer; prefer the CoT over nothing.
        if not content:
            content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
        return LLMResponse(content=content, model=self.slot.model, usage=data.get("usage", {}), raw=data)

    async def _post(self, payload: dict) -> dict:
        r = await self._client.post("/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()


# Give the identity block ONLY to roles that generate user-facing PROSE:
# "base" (fast/thinking/self-consistency), "agent", and the whole MoA prose chain
# (moa_proposer_*/moa_refiner/moa_aggregator) so a council answer actually reflects
# who Metis is. The STRICT-JSON / scoring agents (council intent_parser_*/
# constraint_extractor/ambiguity_hunter/red_team/synthesizer, verifier "judge",
# "router") stay clean — a long identity there perturbs their JSON and drags
# TaskSpec confidence down → spurious clarification.
def _wants_identity(role: str) -> bool:
    # base = fast/thinking/self-consistency; agent = agent loop; moa_aggregator =
    # the council's FINAL answer. NOT the MoA proposers/refiner (giving them the
    # identity made them mimic structured output → JSON leaked into answers).
    return role in ("base", "agent", "moa_aggregator")


class _IdentityProvider(LLMProvider):
    """Prepend an operator identity/self-knowledge block to the system message of
    EVERY call. Placed outermost by ``create_provider`` so it reaches all routes
    (fast, thinking, council, MoA, agent, vision) through the one shared chokepoint
    — ``complete()``. No-op when ``identity`` is empty. It only augments the SYSTEM
    position (trusted operator config); it never touches user input, the canary, or
    the untrusted-content boundary, so prompt-injection defenses are unchanged."""

    def __init__(self, inner: LLMProvider, identity: str):
        self._inner = inner
        self._identity = (identity or "").strip()

    async def complete(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        if not self._identity:
            return await self._inner.complete(messages, temperature=temperature, max_tokens=max_tokens)
        out = list(messages)
        for i, m in enumerate(out):
            if m.role == "system" and isinstance(m.content, str):
                out[i] = Message("system", f"{self._identity}\n\n{m.content}")
                break
        else:
            out = [Message("system", self._identity), *out]
        return await self._inner.complete(out, temperature=temperature, max_tokens=max_tokens)

    async def aclose(self) -> None:
        inner_close = getattr(self._inner, "aclose", None)
        if inner_close:
            await inner_close()


def create_provider(
    slot: ModelSlot,
    config: Optional[RuntimeConfig] = None,
) -> LLMProvider:
    if slot.provider == ProviderKind.MOCK:
        if not config or not config.allow_test_provider:
            raise RuntimeError(
                "Mock provider is test-only. Set allow_test_provider=true in test config."
            )
        from tests.support.mock_provider import MockProvider
        return MockProvider(slot)

    inner: LLMProvider
    if slot.provider == ProviderKind.ANTHROPIC:
        from metis.models.anthropic import AnthropicProvider
        inner = AnthropicProvider(slot)
    elif config and config.distributed and config.cluster_config:
        from metis.distributed.registry import NodeRegistry
        from metis.distributed.remote_provider import RemoteLLMProvider
        registry = _get_registry(config)
        node = registry.resolve_for_slot(node_id=slot.node_id, role=slot.name, model=slot.model)
        if node:
            inner = RemoteLLMProvider(slot, node, registry=registry, security=registry.cluster.security)
        else:
            inner = OpenAICompatProvider(slot)
    else:
        inner = OpenAICompatProvider(slot)

    endpoint = f"{slot.base_url}:{slot.model}"
    if config:
        from metis.observability.logging.module_logger import observe_provider
        inner = observe_provider(inner, slot, config, module_role=slot.name)

    if config and config.economy.enabled:
        from metis.economy.tracked import TrackedProvider
        inner = TrackedProvider(inner, slot)
    # Outermost: stamp the operator identity onto the ANSWER-producing roles only
    # (keeps internal council/verify/router agents clean; no-op when unset).
    if config and getattr(config, "identity", "").strip() and _wants_identity(slot.name):
        inner = _IdentityProvider(inner, config.identity)
    return inner


_registry_cache: dict = {}


def _get_registry(config: RuntimeConfig):
    key = str(config.cluster_config)
    if key not in _registry_cache:
        from metis.distributed.registry import NodeRegistry
        _registry_cache[key] = NodeRegistry.from_yaml(config.cluster_config)
    return _registry_cache[key]


def clear_registry_cache() -> None:
    _registry_cache.clear()


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise
