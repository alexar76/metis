"""Production-hardened worker node server."""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any, Dict, List, Optional

from starlette.requests import Request

from metis.config import ModelSlot, ProviderKind, SecurityConfig
from metis.distributed.protocol import HealthResponse, InvokeRequest, InvokeResponse
from metis.distributed.security import (
    SecuritySettings,
    resolve_api_key,
    verify_request_signature,
)
from metis.models.provider import Message, create_provider
from metis.security.audit import log_security_event
from metis.security.ratelimit import RateLimiter

logger = logging.getLogger("metis.distributed.server")

_MAX_BODY = 512_000


def _require_fastapi():
    try:
        import fastapi
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "FastAPI and uvicorn required. Install: pip install 'metis[distributed]'"
        ) from exc
    return fastapi, uvicorn


def create_app(
    *,
    node_id: str = "local-node",
    models: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    local_slot: Optional[ModelSlot] = None,
    api_key_env: Optional[str] = None,
    security: Optional[SecuritySettings] = None,
    production: bool = False,
    sec_config: Optional[SecurityConfig] = None,
) -> Any:
    fastapi, _ = _require_fastapi()
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app = FastAPI(title=f"Metis Node {node_id}", version="0.1.0")
    sec = security or SecuritySettings()
    sc = sec_config or SecurityConfig()
    slot = local_slot or ModelSlot(
        name=node_id,
        provider=ProviderKind.OLLAMA,
        model=models[0] if models else "qwen3:8b",
    )
    provider = create_provider(slot)
    expected_key = resolve_api_key(api_key_env, fallback="")
    limiter = RateLimiter(sc.rate_limit)

    if sc.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=sc.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Metis-Timestamp", "X-Metis-Signature"],
        )

    def _check_auth(authorization: Optional[str], client_ip: str) -> str:
        if production and not expected_key:
            raise HTTPException(status_code=500, detail="Production requires API key env var")
        token = ""
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
        if expected_key:
            if not token or not hmac.compare_digest(token, expected_key):
                log_security_event("auth_failed", severity="warning", details={"ip": client_ip})
                raise HTTPException(status_code=403, detail="Invalid API key")
        elif production:
            raise HTTPException(status_code=401, detail="Authentication required")
        allowed, retry = limiter.allow(limiter.client_key(client_ip, token))
        if not allowed:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded, retry in {retry}s")
        return token

    async def _read_body(http_request: Request) -> bytes:
        body = await http_request.body()
        if len(body) > sc.max_request_body_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
        return body

    async def _check_signature(http_request: Request, body: bytes) -> None:
        if sec.request_signing:
            secret = sec.hmac_secret()
            if secret:
                ts = http_request.headers.get("X-Metis-Timestamp", "")
                sig = http_request.headers.get("X-Metis-Signature", "")
                if not verify_request_signature(body, ts, sig, secret):
                    raise HTTPException(status_code=401, detail="Invalid signature")

    @app.get("/metis/health")
    async def health(authorization: Optional[str] = Header(None)) -> HealthResponse:
        _check_auth(authorization, "healthcheck")
        return HealthResponse(status="healthy", node_id=node_id, models=models or [slot.model], roles=roles or [])

    @app.post("/metis/invoke")
    async def invoke(http_request: Request, authorization: Optional[str] = Header(None)) -> InvokeResponse:
        ip = http_request.client.host if http_request.client else "unknown"
        _check_auth(authorization, ip)
        body = await _read_body(http_request)
        await _check_signature(http_request, body)
        try:
            payload = InvokeRequest(**json.loads(body))
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        messages = [Message(m.role, m.content) for m in payload.messages]
        resp = await provider.complete(messages, temperature=payload.temperature, max_tokens=payload.max_tokens)
        return InvokeResponse(content=resp.content, model=resp.model, usage=resp.usage, node_id=node_id)

    @app.post("/v1/chat/completions")
    async def openai_proxy(http_request: Request, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
        ip = http_request.client.host if http_request.client else "unknown"
        _check_auth(authorization, ip)
        body = await _read_body(http_request)
        await _check_signature(http_request, body)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        messages = [Message(m["role"], m["content"]) for m in data.get("messages", [])]
        resp = await provider.complete(messages, temperature=data.get("temperature"), max_tokens=data.get("max_tokens"))
        return {
            "id": f"chatcmpl-{node_id}",
            "object": "chat.completion",
            "model": resp.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": resp.content}, "finish_reason": "stop"}],
            "usage": resp.usage,
        }

    return app


def serve_node(
    *,
    host: str = "127.0.0.1",
    port: int = 8443,
    node_id: str = "local-node",
    models: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    provider: ProviderKind = ProviderKind.OLLAMA,
    model: str = "qwen3:8b",
    base_url: str = "http://localhost:11434/v1",
    api_key: str = "ollama",
    api_key_env: Optional[str] = None,
    security: Optional[SecuritySettings] = None,
    production: bool = False,
) -> None:
    _, uvicorn = _require_fastapi()
    slot = ModelSlot(name=node_id, provider=provider, model=model, base_url=base_url, api_key=api_key)
    app = create_app(
        node_id=node_id,
        models=models or [model],
        roles=roles,
        local_slot=slot,
        api_key_env=api_key_env,
        security=security,
        production=production,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
