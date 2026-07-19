"""Reasoning models (deepseek-v4-*) must reliably return clean, complete `content`.

The provider splits CoT (reasoning_content) from the answer (content); a tight
max_tokens budget can starve the answer. These tests lock in that the provider
(a) uses the returned content when present, (b) retries with a bigger budget when a
reasoning model truncates to an empty answer, (c) proactively raises the budget floor
on subsequent calls, and (d) never hands back a blank answer.
"""

from __future__ import annotations

from metis.config import ProviderKind
from metis.models.provider import ModelSlot, OpenAICompatProvider, Message


def _slot(max_tokens=1000):
    return ModelSlot(
        name="base", provider=ProviderKind.OPENAI_COMPAT, model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/v1", api_key="k", max_tokens=max_tokens,
    )


def _script(provider, responses):
    """Monkeypatch _post to return scripted responses and record sent payloads."""
    sent = []

    async def fake_post(payload):
        sent.append(dict(payload))
        return responses[min(len(sent) - 1, len(responses) - 1)]

    provider._post = fake_post
    return sent


def _resp(content=None, reasoning=None, finish="stop"):
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {}}


async def test_plain_content_used_and_no_reasoning_flag():
    p = OpenAICompatProvider(_slot())
    _script(p, [_resp(content="42")])
    out = await p.complete([Message("user", "q")])
    assert out.content == "42"
    assert p._reasoning_model is False


async def test_reasoning_content_present_sets_flag_but_uses_answer():
    p = OpenAICompatProvider(_slot())
    _script(p, [_resp(content="391", reasoning="17*23 = 391")])
    out = await p.complete([Message("user", "q")])
    assert out.content == "391"          # the ANSWER, never the CoT
    assert p._reasoning_model is True


async def test_truncated_empty_answer_retries_with_bigger_budget_and_returns_clean_content():
    p = OpenAICompatProvider(_slot(max_tokens=1000))
    sent = _script(p, [
        _resp(content="", reasoning="thinking..." * 50, finish="length"),  # CoT ate the budget
        _resp(content="the clean final answer", reasoning="...", finish="stop"),
    ])
    out = await p.complete([Message("user", "q")])
    assert out.content == "the clean final answer"   # clean, not blank, not CoT
    assert len(sent) == 2                             # it retried
    assert sent[1]["max_tokens"] > sent[0]["max_tokens"]  # with a larger budget


async def test_budget_floor_applied_on_subsequent_calls_after_detection():
    p = OpenAICompatProvider(_slot(max_tokens=500))
    sent = _script(p, [_resp(content="a", reasoning="r"), _resp(content="b", reasoning="r")])
    await p.complete([Message("user", "q1")])            # detects reasoning model
    await p.complete([Message("user", "q2")])            # next call gets the floor
    assert sent[0]["max_tokens"] == 500                  # first call: as requested
    assert sent[1]["max_tokens"] >= p._REASONING_TOKEN_FLOOR


async def test_never_returns_blank_last_resort_uses_reasoning():
    # Empty content but finish!="length" (no retry path) — must still not be blank.
    p = OpenAICompatProvider(_slot())
    sent = _script(p, [_resp(content="", reasoning="the reasoning text", finish="stop")])
    out = await p.complete([Message("user", "q")])
    assert out.content == "the reasoning text"
    assert len(sent) == 1                                # did NOT retry (not a length truncation)
