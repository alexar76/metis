"""Tests for distributed multi-node architecture."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

import httpx
import pytest
import yaml

from metis.agents.council import run_understanding_council
from metis.config import ModelSlot, ProviderKind, RuntimeConfig
from metis.distributed.node import NodeHealth, NodeStatus
from metis.distributed.protocol import InvokeRequest
from metis.distributed.registry import ClusterConfig, NodeRegistry
from metis.distributed.remote_provider import RemoteLLMProvider
from metis.distributed.security import SecuritySettings, build_auth_headers
from metis.models.provider import Message, clear_registry_cache


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_registry_cache()
    yield
    clear_registry_cache()


def _mock_invoke_response(node_id: str, payload: InvokeRequest) -> dict:
    """Return mock JSON matching MockProvider council patterns."""
    system = next((m.content for m in payload.messages if m.role == "system"), "")
    user = next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
    if "IntentParser" in system:
        content = json.dumps({"goal": f"[{node_id}] {user[:60]}", "assumptions": ["ok"]})
    elif "RedTeam" in system:
        content = json.dumps({"wrong_readings": ["alt"], "traps": ["trap"]})
    elif "TaskSynthesizer" in system:
        content = json.dumps({
            "goal": user[:100],
            "constraints": [],
            "non_goals": [],
            "ambiguities": [],
            "success_criteria": ["done"],
            "required_tools": [],
            "confidence": 0.9,
        })
    else:
        content = json.dumps({"raw": f"[{node_id}] ok"})
    return {"content": content, "model": payload.model, "node_id": node_id}


def _make_cluster_transport(
    fail_nodes: Optional[Set[str]] = None,
    called_nodes: Optional[List[str]] = None,
) -> httpx.AsyncBaseTransport:
    """Mock transport routing by host to simulate 3 worker nodes."""
    fail_nodes = fail_nodes or set()

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or "unknown"
        node_id = host.replace(".test", "")

        if request.url.path == "/metis/health":
            if node_id in fail_nodes:
                return httpx.Response(503, json={"status": "unhealthy"})
            return httpx.Response(200, json={
                "status": "healthy",
                "node_id": node_id,
                "models": ["qwen3:8b"],
                "roles": [],
            })

        if request.url.path == "/metis/invoke":
            if called_nodes is not None:
                called_nodes.append(node_id)
            if node_id in fail_nodes:
                return httpx.Response(503, json={"error": "node down"})
            body = json.loads(request.content)
            payload = InvokeRequest(**body)
            return httpx.Response(200, json=_mock_invoke_response(node_id, payload))

        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def cluster_yaml(tmp_path) -> Path:
    cluster = {
        "coordinator": {"url": "https://coord.test"},
        "nodes": [
            {
                "id": "node-a",
                "url": "http://node-a.test:8443",
                "models": ["qwen3:8b"],
                "roles": ["parser_a", "intent_parser"],
            },
            {
                "id": "node-b",
                "url": "http://node-b.test:8443",
                "models": ["phi4-mini"],
                "roles": ["parser_b", "red_team"],
            },
            {
                "id": "node-c",
                "url": "http://node-c.test:8443",
                "models": ["mistral:7b"],
                "roles": ["parser_c", "synthesizer"],
            },
        ],
        "security": {"tls_verify": False, "request_signing": False},
    }
    path = tmp_path / "cluster.yaml"
    path.write_text(yaml.dump(cluster))
    return path


def _patch_remote_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    """Replace RemoteLLMProvider httpx client factory."""

    original_init = RemoteLLMProvider.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._client = httpx.AsyncClient(transport=transport, verify=False)

    monkeypatch.setattr(RemoteLLMProvider, "__init__", patched_init)


@pytest.mark.asyncio
async def test_council_dispatches_to_three_nodes(cluster_yaml, monkeypatch):
    called: List[str] = []
    transport = _make_cluster_transport(called_nodes=called)
    _patch_remote_client(monkeypatch, transport)

    registry = NodeRegistry.from_yaml(cluster_yaml)
    for h in registry._nodes.values():
        h.status = NodeStatus.HEALTHY

    config = RuntimeConfig(
        distributed=True,
        cluster_config=cluster_yaml,
        provider=ProviderKind.OPENAI_COMPAT,
        council_models=[
            ModelSlot(name="parser_a", model="qwen3:8b", node_id="node-a"),
            ModelSlot(name="parser_b", model="phi4-mini", node_id="node-b"),
            ModelSlot(name="parser_c", model="mistral:7b", node_id="node-c"),
            ModelSlot(name="red_team", model="qwen3:8b", node_id="node-b"),
            ModelSlot(name="synthesizer", model="qwen3:8b", node_id="node-c"),
        ],
    )

    spec = await run_understanding_council(config, "Build a distributed system")
    assert spec.confidence > 0
    assert len(set(called)) >= 2
    assert "node-a" in called or "node-b" in called or "node-c" in called


@pytest.mark.asyncio
async def test_node_failover_on_unhealthy(cluster_yaml, monkeypatch):
    transport = _make_cluster_transport(fail_nodes={"node-a"})
    _patch_remote_client(monkeypatch, transport)

    registry = NodeRegistry.from_yaml(cluster_yaml)
    registry._nodes["node-a"].status = NodeStatus.HEALTHY
    registry._nodes["node-b"].status = NodeStatus.HEALTHY
    registry._nodes["node-c"].status = NodeStatus.HEALTHY

    slot = ModelSlot(name="parser_a", model="qwen3:8b", node_id="node-a")
    node_a = registry.get("node-a")
    provider = RemoteLLMProvider(
        slot,
        node_a,
        registry=registry,
        security=registry.cluster.security,
    )
    provider._client = httpx.AsyncClient(transport=transport, verify=False)

    resp = await provider.complete([
        Message("system", "You are IntentParser agent #1 (parser_a)."),
        Message("user", "test query"),
    ])
    assert "[node-b]" in resp.content or "[node-c]" in resp.content
    await provider.aclose()


@pytest.mark.asyncio
async def test_registry_health_check_marks_unhealthy(cluster_yaml, monkeypatch):
    transport = _make_cluster_transport(fail_nodes={"node-b"})

    async def patched_probe(self, health):
        desc = health.descriptor
        url = f"{desc.url}/metis/health"
        import time
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(transport=transport, verify=False, timeout=5.0) as client:
                r = await client.get(url)
                r.raise_for_status()
            health.status = NodeStatus.HEALTHY
            health.latency_ms = (time.monotonic() - start) * 1000
            health.error = None
            health.consecutive_failures = 0
        except Exception as exc:
            health.consecutive_failures += 1
            health.status = NodeStatus.UNHEALTHY
            health.error = str(exc)
        health.last_check_ms = time.time() * 1000

    import time
    monkeypatch.setattr(NodeRegistry, "_probe", patched_probe)

    registry = NodeRegistry.from_yaml(cluster_yaml)
    await registry.check_health()
    assert registry._nodes["node-a"].is_healthy
    assert not registry._nodes["node-b"].is_healthy
    assert registry._nodes["node-c"].is_healthy


def test_security_headers_bearer_and_signing():
    os.environ["METIS_HMAC_SECRET"] = "test-secret-key"
    security = SecuritySettings(request_signing=True, hmac_secret_env="METIS_HMAC_SECRET")
    body = b'{"model":"test"}'
    headers = build_auth_headers("my-api-key", body=body, security=security)
    assert headers["Authorization"] == "Bearer my-api-key"
    assert "X-Metis-Timestamp" in headers
    assert "X-Metis-Signature" in headers
    assert len(headers["X-Metis-Signature"]) == 64


def test_security_headers_bearer_only():
    headers = build_auth_headers("token123")
    assert headers["Authorization"] == "Bearer token123"
    assert "X-Metis-Signature" not in headers


@pytest.mark.asyncio
async def test_distributed_coordinator_assignments(cluster_yaml):
    registry = NodeRegistry.from_yaml(cluster_yaml)
    for h in registry._nodes.values():
        h.status = NodeStatus.HEALTHY

    from metis.distributed.coordinator import DistributedCoordinator

    config = RuntimeConfig(
        distributed=True,
        cluster_config=cluster_yaml,
        council_models=[
            ModelSlot(name="parser_a", model="qwen3:8b", node_id="node-a"),
            ModelSlot(name="parser_b", model="phi4-mini", node_id="node-b"),
        ],
    )
    coord = DistributedCoordinator(config, registry)
    assignments = coord.node_assignments()
    assert "node-a.test" in assignments["intent_parser_a"]
    assert "node-b.test" in assignments["intent_parser_b"]
