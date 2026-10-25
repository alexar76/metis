"""OpenAI API bridge and auth tests."""

import os

import pytest
from fastapi import HTTPException, Request

from metis.api.auth import get_api_key_from_env, is_production_mode, verify_api_key
from metis.api.bridge import (
    MODEL_ROUTE_MAP,
    AVAILABLE_MODELS,
    OpenAIMetisBridge,
    messages_to_query,
    model_to_route,
)
from metis.api.schemas import ChatCompletionRequest, ChatMessage, ModelInfo, ModelsListResponse
from metis.config import ProviderKind, RouteMode, RuntimeConfig
from metis.exoskeleton import Metis


@pytest.fixture
def mock_config(tmp_path):
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )


def test_model_route_map():
    assert MODEL_ROUTE_MAP["metis-fast"] == RouteMode.FAST
    assert MODEL_ROUTE_MAP["metis-council"] == RouteMode.COUNCIL
    assert MODEL_ROUTE_MAP["superbrain-fast"] == RouteMode.FAST


def test_model_to_route_auto():
    assert model_to_route("metis") is None
    assert model_to_route("metis-agent") == RouteMode.AGENT


def test_messages_to_query():
    msgs = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
    ]
    q = messages_to_query(msgs)
    assert "[system]" in q
    assert "Hello" in q


def test_schemas():
    req = ChatCompletionRequest(messages=[ChatMessage(role="user", content="hi")])
    assert req.model == "metis"
    assert req.messages[0].content == "hi"


def test_available_models():
    assert "metis-council" in AVAILABLE_MODELS


@pytest.mark.asyncio
async def test_openai_bridge_process(mock_config):
    bridge = OpenAIMetisBridge(Metis(mock_config))
    result = await bridge.process([{"role": "user", "content": "test"}], model="metis-fast")
    assert result.content
    assert "route" in result.metadata


@pytest.mark.asyncio
async def test_openai_bridge_stream(mock_config):
    bridge = OpenAIMetisBridge(Metis(mock_config))
    chunks = []
    async for chunk in bridge.stream_tokens("hello world", chunk_size=3):
        chunks.append(chunk)
    assert "".join(chunks) == "hello world"


def _request(peer: str = "127.0.0.1", host: str = "localhost", **headers: str) -> Request:
    raw = [(b"host", host.encode())] + [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "client": (peer, 50000), "headers": raw})


@pytest.mark.asyncio
async def test_verify_api_key_no_auth_when_dev(monkeypatch):
    monkeypatch.delenv("METIS_API_KEY", raising=False)
    monkeypatch.delenv("METIS_PRODUCTION", raising=False)
    assert await verify_api_key(_request(), None) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_",
    [
        _request(peer="93.184.216.34"),  # another machine (the server binds 0.0.0.0)
        _request(host="metis.example"),  # a rebinding name
        _request(x_forwarded_for="93.184.216.34"),  # relayed by a proxy on this host
        _request(x_real_ip="93.184.216.34"),
        _request(origin="https://evil.example"),  # a page in the user's browser
        _request(origin="null"),
    ],
)
async def test_keyless_dev_serves_only_this_machine(monkeypatch, request_):
    monkeypatch.delenv("METIS_API_KEY", raising=False)
    monkeypatch.delenv("METIS_PRODUCTION", raising=False)
    monkeypatch.delenv("AIFACTORY_ENV", raising=False)
    with pytest.raises(HTTPException) as exc:
        await verify_api_key(request_, None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_keyless_dev_serves_a_local_page(monkeypatch):
    monkeypatch.delenv("METIS_API_KEY", raising=False)
    monkeypatch.delenv("METIS_PRODUCTION", raising=False)
    assert await verify_api_key(_request(host="127.0.0.1:8080", origin="http://localhost:5173"), None) is None


@pytest.mark.asyncio
async def test_verify_api_key_required_in_production(monkeypatch):
    monkeypatch.setenv("METIS_PRODUCTION", "1")
    monkeypatch.setenv("METIS_API_KEY", "sk-test")
    with pytest.raises(HTTPException) as exc:
        await verify_api_key(_request(), None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_valid(monkeypatch):
    monkeypatch.setenv("METIS_API_KEY", "sk-good")
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="sk-good")
    assert await verify_api_key(_request(peer="93.184.216.34"), creds) == "sk-good"


def test_legacy_env_key(monkeypatch):
    monkeypatch.delenv("METIS_API_KEY", raising=False)
    monkeypatch.setenv("SUPERBRAIN_API_KEY", "legacy-key")
    assert get_api_key_from_env() == "legacy-key"


def test_models_list_response():
    resp = ModelsListResponse(data=[ModelInfo(id="metis", created=1)])
    assert resp.data[0].id == "metis"
