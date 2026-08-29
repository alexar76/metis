"""An empty assistant message is indistinguishable from "nothing to add".

Measured live: a council deliberated for seventeen minutes — 28 model calls, 100k tokens —
and the caller was told "no content". The bridge already carried the status and the verify
score; `_openai_response` dropped them.
"""

from __future__ import annotations

import json

import pytest


def _bridge_result(content: str, metadata: dict | None = None):
    from metis.api.bridge import ChatProcessResult

    return ChatProcessResult(content=content, usage={"total_tokens": 30},
                             metadata=metadata or {})


@pytest.mark.asyncio
async def test_an_empty_answer_is_reported_as_an_abstention(monkeypatch):
    from metis.api import openai_compat as oc
    from metis.api.schemas import ChatCompletionRequest

    class _Bridge:
        async def process(self, messages, *, model="metis", forced_route=None):
            return _bridge_result("", {"status": "low_confidence", "route": "council",
                                       "verify_score": 0.41})

    body = ChatCompletionRequest(model="metis-council",
                                 messages=[{"role": "user", "content": "hard question"}])
    out = await oc.chat_completions(body=body, api_key=None, bridge=_Bridge())

    choice = out.choices[0]
    assert choice.finish_reason == "abstained"
    payload = json.loads(choice.message["content"])
    assert payload["abstained"] is True
    assert payload["status"] == "low_confidence"
    assert payload["verify_score"] == 0.41
    assert "confidence gate" in payload["detail"]


@pytest.mark.asyncio
async def test_a_real_answer_is_untouched(monkeypatch):
    from metis.api import openai_compat as oc
    from metis.api.schemas import ChatCompletionRequest

    class _Bridge:
        async def process(self, messages, *, model="metis", forced_route=None):
            return _bridge_result('{"ok": true}', {"status": "ok"})

    body = ChatCompletionRequest(model="metis-council",
                                 messages=[{"role": "user", "content": "easy"}])
    out = await oc.chat_completions(body=body, api_key=None, bridge=_Bridge())
    assert out.choices[0].message["content"] == '{"ok": true}'
    assert out.choices[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_whitespace_only_counts_as_empty():
    from metis.api import openai_compat as oc
    from metis.api.schemas import ChatCompletionRequest

    class _Bridge:
        async def process(self, messages, *, model="metis", forced_route=None):
            return _bridge_result("   \n\t ", {"status": "empty"})

    body = ChatCompletionRequest(model="metis", messages=[{"role": "user", "content": "x"}])
    out = await oc.chat_completions(body=body, api_key=None, bridge=_Bridge())
    assert out.choices[0].finish_reason == "abstained"
