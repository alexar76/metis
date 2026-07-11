"""FastAPI OpenAI-compatible endpoint tests."""

import pytest
from fastapi.testclient import TestClient

from metis.api.app import create_app
from metis.config import ProviderKind, RuntimeConfig


@pytest.fixture
def client(tmp_path):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )
    return TestClient(create_app(cfg))


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "metis"


def test_list_models(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()["data"]
    ids = [m["id"] for m in data]
    assert "metis-council" in ids


def test_chat_completions(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "metis-fast",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"]
    assert body["usage"]["total_tokens"] > 0


def test_chat_completions_stream(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "metis-fast",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    assert "data:" in r.text


def test_chat_empty_messages(client):
    r = client.post("/v1/chat/completions", json={"model": "metis", "messages": []})
    assert r.status_code == 400
