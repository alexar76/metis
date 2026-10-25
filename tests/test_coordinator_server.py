"""Tests for coordinator HTTP API."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from metis.config import RuntimeConfig
from metis.coordinator_server import create_coordinator_app


@pytest.fixture
def coordinator_app(monkeypatch):
    monkeypatch.setenv("METIS_API_KEY", "test-coordinator-key")
    cfg = RuntimeConfig(
        production=True,
        allow_test_provider=True,
        provider="mock",
        base_model="test",
    )
    return create_coordinator_app(config=cfg, production=True)


@pytest.mark.asyncio
async def test_health_endpoint(coordinator_app):
    transport = ASGITransport(app=coordinator_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["service"] == "coordinator"


@pytest.mark.asyncio
async def test_query_requires_auth(coordinator_app):
    transport = ASGITransport(app=coordinator_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/v1/query", json={"query": "hello"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_query_rejects_without_key_in_production(monkeypatch):
    monkeypatch.delenv("METIS_API_KEY", raising=False)
    monkeypatch.delenv("COGNITIVE_API_KEY", raising=False)
    cfg = RuntimeConfig(production=True, allow_test_provider=True, provider="mock", base_model="test")
    app = create_coordinator_app(config=cfg, production=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/query",
            json={"query": "hello"},
            headers={"Authorization": "Bearer wrong"},
        )
    assert r.status_code in (403, 500)


@pytest.mark.asyncio
async def test_keyless_dev_coordinator_serves_only_its_own_machine(monkeypatch):
    for name in ("METIS_API_KEY", "SUPERBRAIN_API_KEY", "COGNITIVE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    cfg = RuntimeConfig(production=False, allow_test_provider=True, provider="mock", base_model="test")
    app = create_coordinator_app(config=cfg)
    # Another machine: the coordinator binds 0.0.0.0 by default.
    transport = ASGITransport(app=app, client=("93.184.216.34", 40000))
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        r = await client.post("/v1/query", json={"query": "hello"})
    assert r.status_code == 401
    # A proxy on this host relaying someone else.
    transport = ASGITransport(app=app, client=("127.0.0.1", 40000))
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        r = await client.post("/v1/query", json={"query": "hello"}, headers={"X-Real-IP": "93.184.216.34"})
    assert r.status_code == 401
