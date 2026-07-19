"""Coordinator HTTP API — runs the Metis exoskeleton as a service."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from metis.config import RouteMode, RuntimeConfig, SecurityConfig
from metis.exoskeleton import RunStatus, Metis
from metis.security.audit import log_security_event
from metis.security.ratelimit import RateLimiter

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[misc,assignment]
    Field = None  # type: ignore[misc,assignment]

try:
    from starlette.requests import Request as StarletteRequest
except ImportError:  # pragma: no cover
    StarletteRequest = None  # type: ignore[misc,assignment]

logger = logging.getLogger("metis.coordinator_server")

_MAX_BODY = 512_000


class CoordinatorQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=100_000)
    route: Optional[str] = None


def _require_fastapi():
    try:
        import fastapi
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "FastAPI and uvicorn required. Install: pip install 'metis[distributed]'"
        ) from exc
    return fastapi, uvicorn


def _resolve_api_key() -> str:
    for env_name in ("METIS_API_KEY", "SUPERBRAIN_API_KEY", "COGNITIVE_API_KEY"):
        key = os.environ.get(env_name)
        if key:
            return key
    return ""


def create_coordinator_app(
    *,
    config: Optional[RuntimeConfig] = None,
    config_path: Optional[str | Path] = None,
    production: bool = False,
    sec_config: Optional[SecurityConfig] = None,
) -> Any:
    fastapi, _ = _require_fastapi()
    from fastapi import Body, FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    cfg = config
    if cfg is None and config_path:
        cfg = RuntimeConfig.from_yaml(config_path)
    cfg = cfg or RuntimeConfig()
    if production:
        cfg.production = True

    sc = sec_config or cfg.security
    expected_key = _resolve_api_key()
    limiter = RateLimiter(sc.rate_limit)

    app = FastAPI(title="Metis Coordinator", version="0.1.0")

    brain = Metis(cfg)
    from metis.api.bridge import OpenAIMetisBridge
    from metis.api.openai_compat import router as openai_router

    app.state.config = cfg
    app.state.brain = brain
    app.state.bridge = OpenAIMetisBridge(brain)
    app.include_router(openai_router, prefix="/v1")

    if sc.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=sc.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def _check_auth(authorization: Optional[str], client_ip: str) -> str:
        if cfg.production and not expected_key:
            raise HTTPException(status_code=500, detail="Production requires API key env var")
        token = ""
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
        if expected_key:
            if not token or not hmac.compare_digest(token, expected_key):
                log_security_event("auth_failed", severity="warning", details={"ip": client_ip})
                raise HTTPException(status_code=403, detail="Invalid API key")
        elif cfg.production:
            raise HTTPException(status_code=401, detail="Authentication required")
        allowed, retry = limiter.allow(limiter.client_key(client_ip, token))
        if not allowed:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded, retry in {retry}s")
        return token

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "healthy",
            "service": "coordinator",
            "production": cfg.production,
            "distributed": cfg.distributed,
        }

    @app.post("/v1/query")
    async def query_endpoint(
        req: StarletteRequest,
        authorization: Optional[str] = Header(None),
        payload: CoordinatorQueryRequest = Body(...),
    ) -> JSONResponse:
        ip = req.client.host if req.client else "unknown"
        _check_auth(authorization, ip)
        if len(payload.query) > sc.max_user_input_chars:
            raise HTTPException(status_code=413, detail="Query too long")

        route = None
        if payload.route:
            try:
                route = RouteMode(payload.route)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid route: {payload.route}") from exc

        brain = Metis(cfg)
        result = await brain.run(payload.query, route=route)
        status_code = 200
        if result.status == RunStatus.ERROR:
            status_code = 500
        elif result.status == RunStatus.NEEDS_CLARIFICATION:
            status_code = 422

        return JSONResponse(
            status_code=status_code,
            content={
                "answer": result.answer,
                "status": result.status.value,
                "route": result.route.value,
                "verify_score": result.verify_score,
                "clarifications": result.clarifications,
                "task_spec": result.task_spec.model_dump() if result.task_spec else None,
                "metadata": result.metadata,
            },
        )

    return app


def serve_coordinator(
    *,
    host: str = "0.0.0.0",
    port: int = 8080,
    config_path: Optional[str | Path] = None,
    production: bool = False,
) -> None:
    _, uvicorn = _require_fastapi()
    app = create_coordinator_app(config_path=config_path, production=production)
    uvicorn.run(app, host=host, port=port, log_level="info")
