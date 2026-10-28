"""FastAPI OpenAI-compatible endpoint tests."""

import pytest
from fastapi.testclient import TestClient

from metis.api.app import create_app
from metis.config import ProviderKind, RuntimeConfig

pytestmark = pytest.mark.usefixtures("local_http_opt_in")


@pytest.fixture
def client(tmp_path):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )
    return TestClient(create_app(cfg), client=("127.0.0.1", 50000), base_url="http://localhost")


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


def test_keyless_http_refuses_loopback_without_explicit_relay_trust(client, monkeypatch):
    for name in ("METIS_API_KEY", "SUPERBRAIN_API_KEY", "COGNITIVE_API_KEY", "METIS_PRODUCTION",
                 "AIFACTORY_ENV", "METIS_LOCAL_RELAY", "METIS_LOCAL_UNVERIFIED"):
        monkeypatch.delenv(name, raising=False)
    payload = {"model": "metis-fast", "messages": [{"role": "user", "content": "Hello"}]}
    assert client.post("/v1/chat/completions", json=payload).status_code == 401
    # Credentials work with secure defaults; no local TCP opt-in is needed.
    monkeypatch.setenv("METIS_API_KEY", "test-local-bearer")
    assert client.post("/v1/chat/completions", json=payload,
                       headers={"Authorization": "Bearer test-local-bearer"}).status_code == 200
