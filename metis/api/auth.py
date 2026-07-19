"""API key authentication for the OpenAI-compatible serve endpoint."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("metis.api.auth")

_bearer = HTTPBearer(auto_error=False)

# Emit the "paid endpoints are open" warning only once per process.
_unauth_warning_emitted = False


def _resolve_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def get_api_key_from_env() -> Optional[str]:
    return _resolve_env("METIS_API_KEY", "SUPERBRAIN_API_KEY", "COGNITIVE_API_KEY")


def is_production_mode() -> bool:
    val = _resolve_env(
        "METIS_PRODUCTION",
        "SUPERBRAIN_PRODUCTION",
        "COGNITIVE_PRODUCTION",
        # Ecosystem-standard prod signals — a normal AIFACTORY prod deploy must
        # flip metis into production mode (fail-closed on the paid endpoints).
        "AIFACTORY_PROD",
        "AIFACTORY_PRODUCTION",
    ) or ""
    if val.lower() in ("1", "true", "yes"):
        return True
    env = (os.environ.get("AIFACTORY_ENV") or "").lower()
    return env in ("production", "prod", "live")


async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> Optional[str]:
    """Validate Bearer token when production mode or key is configured."""
    expected = get_api_key_from_env()
    production = is_production_mode()

    if not production and not expected:
        global _unauth_warning_emitted
        if not _unauth_warning_emitted:
            _unauth_warning_emitted = True
            logger.warning(
                "Metis paid endpoints (/v1/verify, /v1/verify/stream, /aimarket/invoke) "
                "are serving UNAUTHENTICATED: no API key configured and not in production "
                "mode. Set METIS_API_KEY before exposing this service."
            )
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
