"""Request/response schemas for inter-node communication."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessagePayload(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)
    content: str = Field(..., max_length=100_000)


class InvokeRequest(BaseModel):
    """RPC payload sent from coordinator to a worker node."""

    model: str = Field(..., min_length=1, max_length=256)
    messages: List[MessagePayload] = Field(..., min_length=1, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=100_000)
    request_id: Optional[str] = Field(None, max_length=128)
    caller_node: Optional[str] = Field(None, max_length=128)


class InvokeResponse(BaseModel):
    content: str
    model: str
    usage: Dict[str, Any] = Field(default_factory=dict)
    node_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    node_id: str
    models: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    version: str = "0.1.0"


class NodeRegistration(BaseModel):
    """Optional dynamic registration payload."""

    node_id: str
    url: str
    models: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)


class ClusterStatusResponse(BaseModel):
    coordinator_url: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
