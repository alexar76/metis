"""Node descriptor and health state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class NodeStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


@dataclass
class NodeDescriptor:
    """A worker node hosting one or more model endpoints."""

    id: str
    url: str
    models: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    api_key_env: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)

    def supports_model(self, model: str) -> bool:
        if not self.models:
            return True
        return any(model == m or model.startswith(m) for m in self.models)

    def supports_role(self, role: str) -> bool:
        if not self.roles:
            return True
        return role in self.roles or role.split("_")[0] in self.roles


@dataclass
class NodeHealth:
    descriptor: NodeDescriptor
    status: NodeStatus = NodeStatus.UNKNOWN
    last_check_ms: float = 0.0
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    consecutive_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.status == NodeStatus.HEALTHY
