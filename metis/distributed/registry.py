"""Node registry: discovery, health checks, failover."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml
from pydantic import BaseModel, Field

from metis.distributed.node import NodeDescriptor, NodeHealth, NodeStatus
from metis.distributed.protocol import HealthResponse
from metis.distributed.security import (
    SecuritySettings,
    build_auth_headers,
    httpx_verify_setting,
    resolve_api_key,
)


from metis.mcp.config import MCPServerConfig


class CoordinatorConfig(BaseModel):
    url: Optional[str] = None


class NodeConfig(BaseModel):
    id: str
    url: str
    api_key_env: Optional[str] = None
    models: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)


class ClusterConfig(BaseModel):
    coordinator: CoordinatorConfig = Field(default_factory=CoordinatorConfig)
    nodes: List[NodeConfig] = Field(default_factory=list)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    mcp_ecosystem_presets: List[str] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ClusterConfig:
        with open(path) as f:
            data: Dict[str, Any] = yaml.safe_load(f) or {}
        return cls(**data)


class NodeRegistry:
    """Register, discover, and health-check worker nodes with failover."""

    def __init__(
        self,
        cluster: ClusterConfig,
        *,
        source_id: str = "coordinator",
        health_timeout: float = 5.0,
    ):
        self.cluster = cluster
        self.source_id = source_id
        self.health_timeout = health_timeout
        self._nodes: Dict[str, NodeHealth] = {}
        self._lock = asyncio.Lock()
        for nc in cluster.nodes:
            desc = NodeDescriptor(
                id=nc.id,
                url=nc.url.rstrip("/"),
                models=list(nc.models),
                roles=list(nc.roles),
                api_key_env=nc.api_key_env,
                capabilities=list(nc.capabilities),
            )
            self._nodes[nc.id] = NodeHealth(descriptor=desc)

    @classmethod
    def from_yaml(cls, path: str | Path, **kwargs: Any) -> NodeRegistry:
        return cls(ClusterConfig.from_yaml(path), **kwargs)

    def register(self, descriptor: NodeDescriptor) -> None:
        self._nodes[descriptor.id] = NodeHealth(descriptor=descriptor)

    async def mark_unhealthy(self, node_id: str, error: str = "") -> None:
        """Thread-safe mark a node unhealthy (called from RemoteLLMProvider)."""
        async with self._lock:
            health = self._nodes.get(node_id)
            if health:
                health.status = NodeStatus.UNHEALTHY
                health.error = error

    def get(self, node_id: str) -> Optional[NodeDescriptor]:
        health = self._nodes.get(node_id)
        return health.descriptor if health else None

    def all_nodes(self) -> List[NodeDescriptor]:
        return [h.descriptor for h in self._nodes.values()]

    def healthy_nodes(self) -> List[NodeDescriptor]:
        return [h.descriptor for h in self._nodes.values() if h.is_healthy]

    def resolve_for_slot(
        self,
        *,
        node_id: Optional[str] = None,
        role: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[NodeDescriptor]:
        """Resolve node by explicit id, then role, then model with failover."""
        candidates: List[NodeDescriptor] = []

        if node_id:
            health = self._nodes.get(node_id)
            if health and health.is_healthy:
                return health.descriptor
            if health:
                candidates.append(health.descriptor)

        for health in self._nodes.values():
            desc = health.descriptor
            if not health.is_healthy and node_id is None:
                continue
            if role and desc.supports_role(role):
                candidates.append(desc)
            elif model and desc.supports_model(model):
                candidates.append(desc)

        if not candidates and node_id:
            health = self._nodes.get(node_id)
            if health:
                candidates.append(health.descriptor)

        if not candidates:
            healthy = self.healthy_nodes()
            if healthy:
                return healthy[0]
            all_nodes = self.all_nodes()
            return all_nodes[0] if all_nodes else None

        for desc in candidates:
            health = self._nodes.get(desc.id)
            if health and health.is_healthy:
                return desc
        return candidates[0]

    def failover_candidates(
        self,
        failed_id: str,
        *,
        role: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[NodeDescriptor]:
        """Return alternate healthy nodes excluding the failed one."""
        healthy = [
            h for h in self._nodes.values()
            if h.descriptor.id != failed_id and h.is_healthy
        ]
        if not healthy:
            return []

        by_role_model = []
        by_model = []
        for health in healthy:
            desc = health.descriptor
            role_ok = not role or desc.supports_role(role)
            model_ok = not model or desc.supports_model(model)
            if role_ok and model_ok:
                by_role_model.append(desc)
            elif model_ok:
                by_model.append(desc)

        if by_role_model:
            return by_role_model
        if by_model:
            return by_model
        return [h.descriptor for h in healthy]

    async def check_health(self, node_id: Optional[str] = None) -> List[NodeHealth]:
        """Probe one or all nodes."""
        async with self._lock:
            targets = (
                [self._nodes[node_id]]
                if node_id and node_id in self._nodes
                else list(self._nodes.values())
            )
            await asyncio.gather(*(self._probe(h) for h in targets))
            return list(self._nodes.values())

    async def _probe(self, health: NodeHealth) -> None:
        desc = health.descriptor
        api_key = resolve_api_key(desc.api_key_env)
        url = f"{desc.url}/metis/health"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self.health_timeout,
                verify=httpx_verify_setting(self.cluster.security),
            ) as client:
                headers = build_auth_headers(api_key, security=self.cluster.security)
                r = await client.get(url, headers=headers)
                r.raise_for_status()
                data = HealthResponse(**r.json())
            health.status = (
                NodeStatus.HEALTHY if data.status == "healthy" else NodeStatus.DEGRADED
            )
            health.latency_ms = (time.monotonic() - start) * 1000
            health.error = None
            health.consecutive_failures = 0
        except Exception as exc:
            health.consecutive_failures += 1
            health.status = NodeStatus.UNHEALTHY
            health.error = str(exc)
            health.latency_ms = None
        health.last_check_ms = time.time() * 1000

    def status_report(self) -> Dict[str, Any]:
        return {
            "coordinator_url": self.cluster.coordinator.url,
            "nodes": [
                {
                    "id": h.descriptor.id,
                    "url": h.descriptor.url,
                    "status": h.status.value,
                    "models": h.descriptor.models,
                    "roles": h.descriptor.roles,
                    "latency_ms": h.latency_ms,
                    "error": h.error,
                }
                for h in self._nodes.values()
            ],
        }
