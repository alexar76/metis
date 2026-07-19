"""Tests for the Metis ecosystem provider surface (/v1/verify + /aimarket/invoke).

Covers the verification envelope, the hub-invoke contract, input coercion,
validation, fail-safe error handling, and — critically — that the surface works
with **no ecosystem configured** (Metis stays fully standalone).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from metis.api.app import create_app
from metis.config import ProviderKind, RuntimeConfig

ENVELOPE_KEYS = {
    "answer",
    "status",
    "verified",
    "verify_score",
    "route",
    "depth",
    "iterations",
    "clarifications",
    "usage",
    "trace_id",
}


@pytest.fixture
def cfg(tmp_path):
    # A plain standalone config: MOCK provider, NO webhook_url, NO hub url, no
    # MCP presets — i.e. no ecosystem present at all.
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg))


def test_verify_envelope_shape(client):
    r = client.post("/v1/verify", json={"input": "What is 2+2?", "route": "council"})
    assert r.status_code == 200
    env = r.json()
    assert ENVELOPE_KEYS.issubset(env.keys())
    assert env["status"] in {"success", "needs_clarification", "error"}
    assert 0.0 <= env["verify_score"] <= 1.0
    assert isinstance(env["verified"], bool)
    assert env["route"] == "council"


def test_verify_min_score_controls_verified_flag(client):
    # Score threshold of 0 => any successful run counts as verified.
    r = client.post("/v1/verify", json={"input": "hi", "route": "council", "min_verify_score": 0.0})
    env = r.json()
    if env["status"] == "success":
        assert env["verified"] is True
    # Threshold of 1.0 => practically nothing is "verified".
    r2 = client.post("/v1/verify", json={"input": "hi", "route": "council", "min_verify_score": 1.0})
    assert r2.json()["verified"] is False


def test_verify_messages_input_coercion(client):
    r = client.post(
        "/v1/verify",
        json={"input": {"messages": [{"role": "user", "content": "Hello there"}]}, "route": "fast"},
    )
    assert r.status_code == 200
    assert r.json()["status"] in {"success", "needs_clarification", "error"}


def test_verify_empty_input_rejected(client):
    assert client.post("/v1/verify", json={"input": "   "}).status_code == 400
    assert client.post("/v1/verify", json={"input": ""}).status_code == 400


def test_verify_bad_route_rejected(client):
    assert client.post("/v1/verify", json={"input": "x", "route": "nope"}).status_code == 400


def test_aimarket_invoke_contract(client):
    r = client.post(
        "/aimarket/invoke",
        json={"input": "ping", "product_id": "metis.cognition", "capability_id": "metis.verify@v1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert ENVELOPE_KEYS.issubset(body["result"].keys())
    assert body["product_id"] == "metis.cognition"
    assert body["capability_id"] == "metis.verify@v1"


def test_aimarket_invoke_sandbox_forces_fast(client):
    r = client.post(
        "/aimarket/invoke",
        json={"input": "probe"},
        headers={"X-AIMarket-Sandbox": "1"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["route"] == "fast"


def test_invoke_accepts_object_input(client):
    r = client.post("/aimarket/invoke", json={"input": {"query": "structured?"}, "route": "fast"})
    assert r.status_code == 200
    assert r.json()["result"]["status"] in {"success", "needs_clarification", "error"}


def test_verify_is_failsafe_on_engine_error(client, monkeypatch):
    """A provider/engine failure must yield a clean error envelope, never a 500."""

    async def _boom(self, *a, **k):  # noqa: ANN001
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr("metis.api.ecosystem.Metis.run", _boom)
    r = client.post("/v1/verify", json={"input": "will fail", "route": "council"})
    assert r.status_code == 200
    env = r.json()
    assert env["status"] == "error"
    assert env["verified"] is False
    assert env["verify_score"] == 0.0
    assert env["answer"] == ""


def test_rate_limit_429(tmp_path):
    """The expensive cognition routes are rate-limited per client (DoS guard)."""
    from metis.security.ratelimit import RateLimitConfig, RateLimiter

    cfg = RuntimeConfig(provider=ProviderKind.MOCK, allow_test_provider=True,
                        memory_dir=tmp_path / "m", thinking_samples=1)
    app = create_app(cfg)
    # Tiny bucket so throttling is deterministic (burst of 1, no refill in-window).
    app.state.eco_limiter = RateLimiter(RateLimitConfig(requests_per_minute=1, burst=1))
    c = TestClient(app)
    codes = [c.post("/v1/verify", json={"input": "hi", "route": "fast"}).status_code for _ in range(4)]
    assert codes[0] == 200 and 429 in codes  # first allowed, then throttled


def test_standalone_no_ecosystem_env(client, cfg):
    """Sanity: the config carries no ecosystem hooks, yet the surface answers."""
    # No webhook / hub URL configured anywhere.
    assert not getattr(cfg.economy, "webhook_url", None)
    r = client.post("/v1/verify", json={"input": "still works alone", "route": "fast"})
    assert r.status_code == 200


def test_metrics_endpoint_prometheus(client):
    """/metrics exposes Prometheus text for scraping/alerting (the monitoring gap)."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert "metis_up 1" in body
    assert "# TYPE metis_up gauge" in body
    assert "metis_knowledge_entries" in body
    assert "metis_circuit_breaker_open" in body
    assert 'metis_build_info{version="0.2.0"} 1' in body
