"""OpenAI API bridge for Metis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from metis.config import RouteMode
from metis.exoskeleton import ExoskeletonResult, Metis
from metis.security import sanitize_user_input

MODEL_ROUTE_MAP: Dict[str, RouteMode] = {
    "metis-fast": RouteMode.FAST,
    "metis-thinking": RouteMode.THINKING,
    "metis-council": RouteMode.COUNCIL,
    "metis-agent": RouteMode.AGENT,
    "superbrain-fast": RouteMode.FAST,
    "superbrain-thinking": RouteMode.THINKING,
    "superbrain-council": RouteMode.COUNCIL,
    "superbrain-agent": RouteMode.AGENT,
    "metis-council-autonomous": RouteMode.COUNCIL,
    "metis-thinking-autonomous": RouteMode.THINKING,
    "superbrain-council-autonomous": RouteMode.COUNCIL,
}

#: Model ids whose caller has NO HUMAN to answer a clarification.
#:
#: The confidence gate is code; the "you are answering an autonomous caller" note in a prompt
#: is prose, and a gate does not read prose. Measured: a remediation run spent six council
#: roles and 37k tokens building a TaskSpec, the gate scored it under threshold, and the whole
#: run was discarded as "no content" — the caller then escalated to the human it was supposed
#: to spare.
#:
#: These ids say, in the one place the gate can see, that a clarification question has nowhere
#: to go. Metis answers with what it understood and reports its confidence; deciding what to do
#: with a low-confidence answer becomes the caller's job, which is right when the caller has a
#: hard gate of its own — the remediation loop re-runs the probe against the candidate build
#: before anything ships, so a poor draft costs a build and cannot reach production.
AUTONOMOUS_MODELS: frozenset[str] = frozenset({
    "metis-council-autonomous",
    "metis-thinking-autonomous",
    "superbrain-council-autonomous",
})

AVAILABLE_MODELS = [
    "metis",
    "metis-fast",
    "metis-thinking",
    "metis-council",
    "metis-council-autonomous",
    "metis-agent",
]


def caller_is_autonomous(model: str) -> bool:
    """Does this caller have a human who could answer a clarification?"""
    return (model or "").lower().strip() in AUTONOMOUS_MODELS


def model_to_route(model: str) -> Optional[RouteMode]:
    """Map OpenAI model name to RouteMode; None means auto-route."""
    key = model.lower().strip()
    if key in ("metis", "superbrain"):
        return None
    return MODEL_ROUTE_MAP.get(key)


def extract_images(messages: List[Dict[str, Any]], max_images: int = 5) -> List[str]:
    """Collect + validate image URLs from OpenAI-style multimodal messages.

    Only ``{"type": "image_url", "image_url": {"url": …}}`` parts are taken;
    each is SSRF/size-validated and the list is capped. Invalid entries drop.
    """
    from metis.security.media import validate_images

    urls: List[str] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "image_url":
                iu = block.get("image_url")
                url = iu.get("url") if isinstance(iu, dict) else iu
                if isinstance(url, str) and url:
                    urls.append(url)
    return validate_images(urls, max_images=max_images)


def messages_to_query(messages: List[Dict[str, Any]]) -> str:
    """Flatten chat messages into a single query string."""
    parts: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        if role == "system":
            parts.append(f"[system]\n{content}")
        else:
            parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


@dataclass
class ChatProcessResult:
    content: str
    usage: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class OpenAIMetisBridge:
    """Wraps Metis with OpenAI chat completion semantics."""

    def __init__(self, brain: Metis) -> None:
        self._brain = brain

    async def process(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str = "metis",
        forced_route: Optional[RouteMode] = None,
        **_kwargs: Any,
    ) -> ChatProcessResult:
        query = messages_to_query(messages)
        sanitized = sanitize_user_input(query).text
        max_images = getattr(self._brain.config, "max_images", 5)
        images = extract_images(messages, max_images) if getattr(
            self._brain.config, "enable_multimodal", True
        ) else []
        result: ExoskeletonResult = await self._brain.run(
            sanitized,
            route=forced_route if forced_route is not None else model_to_route(model),
            images=images or None,
            autonomous_caller=caller_is_autonomous(model),
        )
        calls = int(result.metadata.get("llm_calls", 1))
        usage = {
            "prompt_tokens": calls * 10,
            "completion_tokens": calls * 20,
            "total_tokens": calls * 30,
        }
        return ChatProcessResult(
            content=result.answer,
            usage=usage,
            metadata={
                "route": result.route.value,
                "status": result.status.value,
                "verify_score": result.verify_score,
                **result.metadata,
            },
        )

    async def stream_tokens(
        self, content: str, *, chunk_size: int = 8
    ) -> AsyncIterator[str]:
        for i in range(0, len(content), chunk_size):
            yield content[i : i + chunk_size]
