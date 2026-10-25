"""The built-in Python screen has no operating-system isolation.

Never execute host code for HTTP/WebSocket requests or production deployments.
An explicit private, local development opt-in retains trusted arithmetic demos.
"""
from __future__ import annotations

import os
from contextvars import ContextVar

_public_request: ContextVar[bool] = ContextVar("metis_public_code_request", default=False)


def host_execution_refusal(*, production: bool = False) -> str | None:
    prod_env = os.getenv("METIS_PRODUCTION", "").strip().lower() in {"1", "true", "yes", "on"}
    if production or prod_env or _public_request.get():
        return "Host Python execution is unavailable for public requests and production; use an isolated execution service"
    if os.getenv("METIS_UNSAFE_LOCAL_CODE", "").strip() != "1":
        return "Host Python execution is disabled; trusted private development requires METIS_UNSAFE_LOCAL_CODE=1"
    return None


class DenyPublicHostExecution:
    """Keep the policy active through streaming responses and spawned request tasks."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        token = _public_request.set(True)
        try:
            await self.app(scope, receive, send)
        finally:
            _public_request.reset(token)
