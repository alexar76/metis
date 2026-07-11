"""FastAPI application for the OpenAI-compatible Metis API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI

from metis.api.bridge import OpenAIMetisBridge
from metis.api.ecosystem import router as ecosystem_router
from metis.api.observability_routes import build_observability_router
from metis.api.openai_compat import router as openai_router
from metis.config import RuntimeConfig
from metis.exoskeleton import Metis
from metis.observability.logging.audit import configure_audit
from metis.observability.logging.tracer import init_logging
from metis.observability.reliability.circuit_breaker import all_breaker_status


def _load_config() -> RuntimeConfig:
    path = os.environ.get("METIS_CONFIG_PATH")
    if path:
        return RuntimeConfig.from_yaml(path)
    return RuntimeConfig()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not getattr(app.state, "bridge", None):
        config: RuntimeConfig = app.state.config
        brain = Metis(config)
        app.state.brain = brain
        app.state.bridge = OpenAIMetisBridge(brain)
    yield


def create_app(config: Optional[RuntimeConfig] = None) -> FastAPI:
    """Build the FastAPI app with OpenAI-compatible routes."""
    runtime_config = config or _load_config()

    obs = runtime_config.observability
    init_logging(obs)
    if obs.audit_log_file:
        configure_audit(path=obs.audit_log_file, hash_chain=obs.audit_hash_chain)

    brain = Metis(runtime_config)

    app = FastAPI(
        title="Metis API",
        description="OpenAI-compatible API for the Metis cognitive runtime",
        version="0.2.0",
        lifespan=_lifespan,
    )
    app.state.config = runtime_config
    app.state.brain = brain
    app.state.bridge = OpenAIMetisBridge(brain)

    # Optional CORS — off unless the operator sets security.cors_origins. Lets the
    # 3D "superbrain" landing (a static page) call /v1/chat/completions in-browser.
    if runtime_config.security.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_config.security.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    trace_dir = obs.trace_dir or str(runtime_config.knowledge.store_path.replace("knowledge", "traces"))
    if obs.trace_dir:
        trace_dir = obs.trace_dir
    else:
        trace_dir = "data/traces"

    @app.get("/health")
    async def health() -> dict:
        cfg = app.state.config
        nodes = []
        if cfg.distributed and cfg.cluster_config:
            try:
                from metis.distributed.registry import NodeRegistry
                reg = NodeRegistry.from_yaml(cfg.cluster_config)
                nodes = [
                    {
                        "id": h.descriptor.id,
                        "url": h.descriptor.url,
                        "status": h.status.value,
                        "healthy": h.is_healthy,
                    }
                    for h in reg._nodes.values()
                ]
            except Exception:
                nodes = []
        return {
            "status": "ok",
            "service": "metis",
            "version": "0.2.0",
            "nodes": nodes,
            "circuit_breakers": all_breaker_status(),
            "knowledge_entries": (
                brain._knowledge_store.count() if brain._knowledge_store else 0
            ),
        }

    obs_router = build_observability_router(
        get_knowledge_store=lambda: brain._knowledge_store,
        trace_dir=trace_dir,
    )
    app.include_router(obs_router, prefix="/v1")
    app.include_router(openai_router, prefix="/v1")
    # Ecosystem provider surface (/v1/verify + /aimarket/invoke). Routes carry
    # their own absolute paths, so no prefix. Optional & self-contained — this
    # is the only place Metis exposes the verification envelope to peers.
    from metis.security.ratelimit import RateLimiter
    app.state.eco_limiter = RateLimiter(runtime_config.security.rate_limit)
    app.include_router(ecosystem_router)
    return app


app = create_app()
