"""Remote LLM provider — calls a worker node via secure HTTP RPC."""

from __future__ import annotations

import time
import uuid
from typing import List, Optional

import httpx

from metis.config import ModelSlot
from metis.distributed.node import NodeDescriptor, NodeStatus
from metis.distributed.protocol import InvokeRequest, InvokeResponse, MessagePayload
from metis.distributed.registry import NodeRegistry
from metis.distributed.security import (
    SecuritySettings,
    audit_cross_node_call,
    build_auth_headers,
    httpx_verify_setting,
    resolve_api_key,
)
from metis.models.provider import LLMProvider, LLMResponse, Message


class RemoteLLMProvider(LLMProvider):
    """Implements LLMProvider by invoking a remote cognitive node."""

    def __init__(
        self,
        slot: ModelSlot,
        node: NodeDescriptor,
        *,
        registry: Optional[NodeRegistry] = None,
        security: Optional[SecuritySettings] = None,
        source_id: str = "coordinator",
        timeout: float = 120.0,
    ):
        self.slot = slot
        self.node = node
        self.registry = registry
        self.security = security or SecuritySettings()
        self.source_id = source_id
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            verify=httpx_verify_setting(self.security),
            timeout=timeout,
        )

    async def complete(
        self,
        messages: List[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        request_id = str(uuid.uuid4())
        payload = InvokeRequest(
            model=self.slot.model,
            messages=[MessagePayload(role=m.role, content=m.content) for m in messages],
            temperature=temperature if temperature is not None else self.slot.temperature,
            max_tokens=max_tokens or self.slot.max_tokens,
            request_id=request_id,
            caller_node=self.source_id,
        )
        body = payload.model_dump_json().encode("utf-8")
        nodes_to_try = [self.node]
        if self.registry:
            nodes_to_try.extend(
                self.registry.failover_candidates(
                    self.node.id,
                    role=self.slot.name,
                    model=self.slot.model,
                )
            )

        last_error: Optional[Exception] = None
        for node in nodes_to_try:
            try:
                return await self._invoke(node, body, payload, request_id, len(messages))
            except Exception as exc:
                last_error = exc
                if self.registry:
                    # SECURITY: use public API to avoid race on _nodes dict.
                    await self.registry.mark_unhealthy(node.id, str(exc))
                continue

        audit_cross_node_call(
            source=self.source_id,
            target_node=self.node.id,
            model=self.slot.model,
            request_id=request_id,
            status="error",
            error=str(last_error) if last_error else "all nodes failed",
            message_count=len(messages),
        )
        raise RuntimeError(f"Remote invoke failed for slot {self.slot.name}: {last_error}")

    async def _invoke(
        self,
        node: NodeDescriptor,
        body: bytes,
        payload: InvokeRequest,
        request_id: str,
        message_count: int,
    ) -> LLMResponse:
        api_key = resolve_api_key(node.api_key_env, fallback=self.slot.api_key)
        headers = build_auth_headers(api_key, body=body, security=self.security)
        url = f"{node.url.rstrip('/')}/metis/invoke"
        start = time.monotonic()
        r = await self._client.post(url, content=body, headers=headers)
        r.raise_for_status()
        latency_ms = (time.monotonic() - start) * 1000
        data = InvokeResponse(**r.json())
        audit_cross_node_call(
            source=self.source_id,
            target_node=node.id,
            model=self.slot.model,
            request_id=request_id,
            status="ok",
            latency_ms=latency_ms,
            message_count=message_count,
        )
        return LLMResponse(
            content=data.content,
            model=data.model,
            usage=data.usage,
            raw=data.model_dump(),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
