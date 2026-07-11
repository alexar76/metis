"""API key authentication for the OpenAI-compatible serve endpoint."""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def _resolve_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def get_api_key_from_env() -> Optional[str]:
    return _resolve_env("METIS_API_KEY", "SUPERBRAIN_API_KEY", "COGNITIVE_API_KEY")


def is_production_mode() -> bool:
    val = _resolve_env("METIS_PRODUCTION", "SUPERBRAIN_PRODUCTION", "COGNITIVE_PRODUCTION") or ""
    return val.lower() in ("1", "true", "yes")


async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> Optional[str]:
    """Validate Bearer token when production mode or key is configured."""
    expected = get_api_key_from_env()
    production = is_production_mode()

    if not production and not expected:
        return None

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Bearer sk-...",
        )

    token = credentials.credentials
    if not expected:
        if production:
            raise HTTPException(
                status_code=500,
                detail="METIS_API_KEY must be set in production mode",
            )
        # SECURITY: fail-closed — never accept an unverified token. In dev without
        # a configured key, auth is skipped via the early return at line 39-40.
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not hmac.compare_digest(token, expected):  # constant-time
        raise HTTPException(status_code=401, detail="Invalid API key")

    return token
