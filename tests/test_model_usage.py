import json

import httpx
import pytest

from metis.config import ModelSlot, ProviderKind
from metis.models.provider import Message, OpenAICompatProvider, _IdentityProvider


@pytest.mark.asyncio
async def test_reasoning_retry_logs_each_dispatch_and_preserves_mcp(monkeypatch, tmp_path):
    path = tmp_path / "model_usage.jsonl"
    monkeypatch.setenv("METIS_MODEL_USAGE_LOG", str(path))
    posted = []

    def respond(request):
        payload = json.loads(request.content)
        posted.append(payload)
        assert payload["usage"] == {"include": True}
        assert payload["messages"][0] == {"role": "system", "content": "identity\n\nprivate catalog"}
        return httpx.Response(200, json={
            "id": f"gen-{len(posted)}",
            "choices": [{"message": {"content": "" if len(posted) == 1 else "answer",
                                     "reasoning_content": "private reasoning"},
                         "finish_reason": "length" if len(posted) == 1 else "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "cost": 0.001,
                      "prompt_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 2}},
        })

    slot = ModelSlot(name="base", provider=ProviderKind.OPENAI_COMPAT, model="reasoner",
                     base_url="https://openrouter.ai/api/v1", api_key="fixture-key")
    inner = OpenAICompatProvider(slot)
    await inner.aclose()
    async with httpx.AsyncClient(base_url=slot.base_url, transport=httpx.MockTransport(respond)) as client:
        inner._client = client
        provider = _IdentityProvider(inner, "identity")
        out = await provider.complete([
            Message("system", "private catalog", mcp_tools=(("oracle", "get_score"),)),
            Message("user", "private result", mcp_results=(("oracle", "get_score"),)),
        ])
    assert out.content == "answer"
    raw = path.read_text()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == 2 and rows[0]["call_id"] != rows[1]["call_id"]
    assert [r["provider_generation_id"] for r in rows] == ["gen-1", "gen-2"]
    for row in rows:
        assert row["mcp_servers"] == [{"server": "oracle", "tools": ["get_score"], "result_tools": ["get_score"]}]
        assert (row["cache_read_input_tokens"], row["cache_write_input_tokens"], row["provider_cost_usd"]) == (10, 2, 0.001)
    assert "private" not in raw and "fixture-key" not in raw
