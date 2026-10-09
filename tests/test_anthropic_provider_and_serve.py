"""The native Anthropic adapter and the `metis-serve` entrypoint, once omitted from coverage."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from metis.config import ModelSlot, ProviderKind
from metis.models.anthropic import AnthropicProvider
from metis.models.provider import Message


def _slot(**overrides) -> ModelSlot:
    base = dict(name="a", provider=ProviderKind.ANTHROPIC, model="model-x",
                base_url="https://api.anthropic.com/v1", api_key="k-test")
    base.update(overrides)
    return ModelSlot(**base)


def _mock(provider: AnthropicProvider, handler) -> None:
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                         headers=dict(provider._client.headers))


@pytest.mark.asyncio
async def test_messages_request_and_response_mapping():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "model-x-2",
            "content": [{"type": "text", "text": "hel"}, {"type": "tool_use"}, {"type": "text", "text": "lo"}],
            "usage": {"input_tokens": 7, "output_tokens": 2},
        })

    provider = AnthropicProvider(_slot())
    _mock(provider, handler)
    out = await provider.complete(
        [Message("system", "be brief"), Message("user", "hi"), Message("assistant", "yo"), Message("tool", "x")],
        temperature=0.2, max_tokens=50,
    )
    await provider.aclose()

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "k-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["system"] == "be brief"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    assert seen["body"]["max_tokens"] == 50 and seen["body"]["temperature"] == 0.2
    assert out.content == "hello" and out.model == "model-x-2"
    assert out.usage == {"prompt_tokens": 7, "completion_tokens": 2, "input_tokens": 7, "output_tokens": 2}


@pytest.mark.asyncio
async def test_omit_temperature_and_http_errors(monkeypatch):
    slot = _slot()
    monkeypatch.setattr(slot, "omit_temperature", True, raising=False)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(529, json={"error": "overloaded"})

    provider = AnthropicProvider(slot)
    _mock(provider, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete([Message("user", "hi")])
    await provider.aclose()
    assert "temperature" not in seen["body"]


def test_messages_url_is_derived_from_the_base_url():
    assert AnthropicProvider(_slot(base_url="https://proxy.example/v1"))._url == "https://proxy.example/v1/messages"
    assert AnthropicProvider(_slot(base_url="https://proxy.example"))._url == "https://proxy.example/v1/messages"
    assert AnthropicProvider(_slot(base_url="https://proxy.example/v1/messages"))._url == (
        "https://proxy.example/v1/messages"
    )


def test_serve_main_builds_the_api_and_runs_it(monkeypatch):
    import uvicorn

    from metis import serve

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setattr("metis.api.app.create_app", lambda cfg: ("app", cfg.production))
    monkeypatch.setattr(sys, "argv", ["metis-serve", "--host", "127.0.0.5", "--port", "8181", "--production"])
    serve.serve_main()
    assert seen["app"] == ("app", True)
    assert seen["host"] == "127.0.0.5" and seen["port"] == 8181
