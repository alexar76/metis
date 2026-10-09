"""The worker node HTTP server — the one cross-host door into a Metis cluster.

It used to sit in the coverage omit list, so its auth, signing, body-limit and rate-limit
paths counted for nothing. Each refusal here is one an attacker would probe for.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from metis.config import RateLimitConfig, SecurityConfig
from metis.distributed import server as node_server
from metis.distributed.security import SecuritySettings
from metis.models.provider import LLMResponse


class _EchoProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, messages, *, temperature=None, max_tokens=None):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return LLMResponse(content="pong:" + str(messages[-1].content), model="echo-1", usage={"total_tokens": 3})


@pytest.fixture
def provider(monkeypatch):
    fake = _EchoProvider()
    monkeypatch.setattr(node_server, "create_provider", lambda slot: fake)
    return fake


def _app(**kwargs):
    return node_server.create_app(node_id="node-a", models=["echo-1"], roles=["worker"], **kwargs)


async def _call(app, method: str, path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _invoke_body(text: str = "ping") -> bytes:
    return json.dumps({"model": "echo-1", "messages": [{"role": "user", "content": text}],
                       "temperature": 0.1, "max_tokens": 5}).encode()


@pytest.mark.asyncio
async def test_open_node_answers_health_and_invoke(provider):
    app = _app()
    r = await _call(app, "GET", "/metis/health")
    assert r.status_code == 200
    assert r.json()["node_id"] == "node-a" and r.json()["models"] == ["echo-1"]

    r = await _call(app, "POST", "/metis/invoke", content=_invoke_body())
    assert r.status_code == 200
    assert r.json()["content"] == "pong:ping" and r.json()["node_id"] == "node-a"
    assert provider.calls[0]["temperature"] == 0.1 and provider.calls[0]["max_tokens"] == 5


@pytest.mark.asyncio
async def test_production_without_a_key_env_refuses_everything(provider):
    r = await _call(_app(production=True), "GET", "/metis/health")
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_wrong_or_missing_key_is_refused(provider, monkeypatch):
    monkeypatch.setenv("NODE_KEY", "s3cret")
    app = _app(api_key_env="NODE_KEY", production=True)

    assert (await _call(app, "GET", "/metis/health")).status_code == 403
    r = await _call(app, "GET", "/metis/health", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403
    r = await _call(app, "GET", "/metis/health", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_oversized_body_is_refused_before_parsing(provider):
    app = _app(sec_config=SecurityConfig(max_request_body_bytes=64))
    r = await _call(app, "POST", "/metis/invoke", content=_invoke_body("x" * 200))
    assert r.status_code == 413
    assert provider.calls == []


@pytest.mark.asyncio
async def test_malformed_bodies_are_400(provider):
    app = _app()
    assert (await _call(app, "POST", "/metis/invoke", content=b"{not json")).status_code == 400
    no_model = json.dumps({"messages": [{"role": "user", "content": "x"}]}).encode()
    assert (await _call(app, "POST", "/metis/invoke", content=no_model)).status_code == 400
    assert (await _call(app, "POST", "/v1/chat/completions", content=b"{not json")).status_code == 400
    assert provider.calls == []


@pytest.mark.asyncio
async def test_rate_limit_answers_429(provider):
    app = _app(sec_config=SecurityConfig(rate_limit=RateLimitConfig(requests_per_minute=1, burst=1)))
    statuses = [(await _call(app, "GET", "/metis/health")).status_code for _ in range(3)]
    assert statuses[0] == 200 and 429 in statuses


@pytest.mark.asyncio
async def test_signed_requests_need_a_valid_fresh_signature(provider, monkeypatch):
    monkeypatch.setenv("NODE_HMAC", "hmac-secret")
    app = _app(security=SecuritySettings(request_signing=True, hmac_secret_env="NODE_HMAC"))
    body = _invoke_body()

    r = await _call(app, "POST", "/metis/invoke", content=body)
    assert r.status_code == 401

    stale = str(int(time.time()) - 3600)
    stale_sig = hmac.new(b"hmac-secret", f"{stale}.".encode() + body, hashlib.sha256).hexdigest()
    r = await _call(app, "POST", "/metis/invoke", content=body,
                    headers={"X-Metis-Timestamp": stale, "X-Metis-Signature": stale_sig})
    assert r.status_code == 401

    ts = str(int(time.time()))
    sig = hmac.new(b"hmac-secret", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    r = await _call(app, "POST", "/metis/invoke", content=body,
                    headers={"X-Metis-Timestamp": ts, "X-Metis-Signature": sig})
    assert r.status_code == 200
    assert provider.calls and provider.calls[0]["messages"][-1].content == "ping"


@pytest.mark.asyncio
async def test_openai_proxy_shape(provider):
    r = await _call(_app(), "POST", "/v1/chat/completions", content=_invoke_body("hi"))
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion" and data["model"] == "echo-1"
    assert data["choices"][0]["message"] == {"role": "assistant", "content": "pong:hi"}


@pytest.mark.asyncio
async def test_cors_is_only_what_was_configured(provider):
    app = _app(sec_config=SecurityConfig(cors_origins=["https://ok.example"]))
    r = await _call(app, "OPTIONS", "/metis/invoke", headers={
        "Origin": "https://ok.example", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "https://ok.example"
    r = await _call(app, "OPTIONS", "/metis/invoke", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") is None


def test_serve_node_hands_the_built_app_to_uvicorn(provider, monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    node_server.serve_node(host="127.0.0.9", port=9443, node_id="n9", model="m9")
    assert seen["host"] == "127.0.0.9" and seen["port"] == 9443
    assert seen["app"].title == "Metis Node n9"
