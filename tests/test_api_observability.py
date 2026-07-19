"""API tests for feedback, traces, and detailed health."""

import pytest
from fastapi.testclient import TestClient

from metis.api.app import create_app
from metis.config import ProviderKind, RuntimeConfig
from metis.observability.trace_store import TraceStore


@pytest.fixture
def client(tmp_path):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
        knowledge={"enabled": True, "store_path": str(tmp_path / "knowledge")},
        observability={"trace_dir": str(tmp_path / "traces")},
    )
    return TestClient(create_app(cfg))


def test_health_detailed(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.2.0"
    assert "circuit_breakers" in data
    assert "knowledge_entries" in data


def test_feedback_requires_auth_in_production(client, monkeypatch, tmp_path):
    monkeypatch.setenv("METIS_PRODUCTION", "1")
    monkeypatch.setenv("METIS_API_KEY", "sk-test")
    resp = client.post("/v1/feedback", json={"trace_id": "t1", "rating": 5})
    assert resp.status_code == 401

    resp = client.post(
        "/v1/feedback",
        json={"trace_id": "t1", "rating": 5, "comment": "good"},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_get_trace(client, tmp_path):
    trace_dir = tmp_path / "traces"
    store = TraceStore(trace_dir)
    store.save({"trace_id": "xyz", "status": "success", "route": "fast", "query": "[redacted]"})

    resp = client.get("/v1/traces/xyz")
    # dev mode — no auth required when no key set
    assert resp.status_code == 200
    assert resp.json()["trace_id"] == "xyz"


def test_get_trace_not_found(client):
    resp = client.get("/v1/traces/nonexistent")
    assert resp.status_code == 404
