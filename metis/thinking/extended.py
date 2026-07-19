"""Test-time compute: extended thinking and self-consistency."""

from __future__ import annotations

import asyncio
import re
from collections import Counter

from metis.models.provider import LLMProvider

THINKING_SYSTEM = """You are a careful reasoner. Use extended thinking before answering.

Format:

step-by-step reasoning, explore alternatives, check assumptions


Your final answer after the thinking block."""


async def extended_thinking(
    provider: LLMProvider,
    query: str,
    *,
    context: str = "",
) -> tuple[str, str]:
    """Single pass with chain-of-thought. Returns (reasoning, answer)."""
    user = _build_user(query, context)
    raw = await provider.complete_text(THINKING_SYSTEM, user, temperature=0.7)
    return _split_thinking(raw)


async def self_consistency(
    provider: LLMProvider,
    query: str,
    *,
    n_samples: int = 3,
    temperature: float = 0.8,
    context: str = "",
) -> tuple[str, list[str]]:
    """N independent reasoning paths, majority vote on answer. Returns (answer, all_reasonings)."""
    user = _build_user(query, context)
    reasonings: list[str] = []
    answers: list[str] = []
    originals: list[str] = []

    # Independent reasoning paths → run them concurrently, not one-by-one.
    raws = await asyncio.gather(*[
        provider.complete_text(THINKING_SYSTEM, user, temperature=temperature)
        for _ in range(n_samples)
    ])
    for raw in raws:
        reasoning, answer = _split_thinking(raw)
        reasonings.append(reasoning)
        originals.append(answer)
        answers.append(_normalize_for_vote(answer))

    counts = Counter(answers)
    winner_norm, _ = counts.most_common(1)[0]
    for orig, norm in zip(originals, answers):
        if norm == winner_norm:
            return orig, reasonings
    return originals[0], reasonings


def _build_user(query: str, context: str) -> str:
    if context:
        return f"Context:\n{context}\n\nQuery:\n{query}"
    return query


def _split_thinking(text: str) -> tuple[str, str]:
    match = re.search(r"(.*?)", text, re.DOTALL | re.IGNORECASE)
    if match:
        reasoning = match.group(1).strip()
        answer = text[match.end():].strip()
        return reasoning, answer or text.strip()
    return "", text.strip()


def _normalize_for_vote(answer: str) -> str:
    return re.sub(r"\s+", " ", answer.strip().lower())[:200]
