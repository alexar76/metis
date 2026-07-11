"""SSRF protection with redirect validation and final URL checks."""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional, Set
from urllib.parse import urlparse

import httpx

_BLOCKED_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.goog",
})

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MAX_REDIRECTS = 3


def _is_private_ip(hostname: str) -> bool:
    try:
        addr = ipaddress.ip_address(hostname)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        pass
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
            ):
                return True
    except (socket.gaierror, OSError):
        return True
    return False


def validate_url(url: str, *, allowed_schemes: Optional[Set[str]] = None) -> str:
    """Validate URL is safe for outbound requests."""
    schemes = allowed_schemes or _ALLOWED_SCHEMES
    parsed = urlparse(url.strip())
    if parsed.scheme not in schemes:
        raise ValueError(f"URL scheme '{parsed.scheme}' is not allowed")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Hostname '{host}' is not allowed")
    if _is_private_ip(host):
        raise ValueError(f"Hostname '{host}' resolves to a private/reserved address")
    return url.strip()


async def safe_get(
    url: str,
    *,
    timeout: float = 15.0,
    max_redirects: int = _MAX_REDIRECTS,
    headers: Optional[dict] = None,
) -> httpx.Response:
    """HTTP GET with SSRF protection on every redirect hop."""
    validate_url(url)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers or {},
    ) as client:
        current = url
        for _ in range(max_redirects + 1):
            validate_url(current)
            resp = await client.get(current)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return resp
                current = str(resp.url.join(location))
                continue
            return resp
        raise ValueError(f"Too many redirects (max {max_redirects})")


async def safe_post(
    url: str,
    *,
    data: Optional[dict] = None,
    timeout: float = 15.0,
    max_redirects: int = _MAX_REDIRECTS,
    headers: Optional[dict] = None,
) -> httpx.Response:
    """HTTP POST with SSRF protection."""
    validate_url(url)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers or {},
    ) as client:
        current = url
        for _ in range(max_redirects + 1):
            validate_url(current)
            resp = await client.post(current, data=data)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return resp
                current = str(resp.url.join(location))
                continue
            return resp
        raise ValueError(f"Too many redirects (max {max_redirects})")
