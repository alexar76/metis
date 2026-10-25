"""API key authentication for the OpenAI-compatible serve endpoint."""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from typing import Optional

from fastapi import HTTPException, Request, Security
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


_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_FORWARDING_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-host")


def _host_is_loopback(hostport: str) -> bool:
    """`localhost[:port]`, `127.0.0.1[:port]` or `[::1][:port]`, as a Host header or netloc."""
    value = hostport.strip().lower()
    if value.startswith("["):
        host = value[1:value.find("]")] if "]" in value else ""
    else:
        host = value.rsplit(":", 1)[0] if value.count(":") == 1 else value
    return host in _LOOPBACK_NAMES


def local_caller(request: Request) -> bool:
    """The machine's own user: a loopback packet with a loopback Host, no forwarding headers
    (behind nginx on this host every caller's packet is from 127.0.0.1) and no Origin but a
    loopback page (a site open in that user's browser can POST here too)."""
    peer = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(peer).is_loopback:
            return False
    except ValueError:
        return False
    if any(h in request.headers for h in _FORWARDING_HEADERS):
        return False
    if not _host_is_loopback(request.headers.get("host", "")):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    scheme, _, rest = origin.strip().partition("://")
    return scheme in ("http", "https") and _host_is_loopback(rest.split("/", 1)[0])


async def verify_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> Optional[str]:
    """Validate Bearer token when production mode or key is configured."""
    expected = get_api_key_from_env()
    production = is_production_mode()

    if not production and not expected:
        # No key outside production: callers on this machine only. Every caller used to be
        # served here, on a port bound to 0.0.0.0 by default, spending the operator's model
        # budget (the class of Vulnetix GCVE-110-PYPI-2026-018883, CWE-306).
        if not local_caller(request):
            raise HTTPException(
                status_code=401,
                detail="No METIS_API_KEY is configured, so only callers on this machine are "
                "served. Set METIS_API_KEY to serve others.",
            )
        global _unauth_warning_emitted
        if not _unauth_warning_emitted:
            _unauth_warning_emitted = True
            logger.warning(
                "Metis paid endpoints (/v1/verify, /v1/verify/stream, /aimarket/invoke) "
                "answer local callers UNAUTHENTICATED: no API key configured and not in "
                "production mode. Set METIS_API_KEY before exposing this service."
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
        # a configured key, a local caller is let in by the early return above.
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not hmac.compare_digest(token, expected):  # constant-time
        raise HTTPException(status_code=401, detail="Invalid API key")

    return token
