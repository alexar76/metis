"""SSRF protection with redirect validation and final URL checks."""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional, Set
from urllib.parse import urljoin, urlparse

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
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain embedded credentials")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Hostname '{host}' is not allowed")
    if _is_private_ip(host):
        raise ValueError(f"Hostname '{host}' resolves to a private/reserved address")
    return url.strip()


def _pinned_target(url: str) -> tuple[str, dict, dict]:
    """Dial the address we checked, preserving Host and TLS server identity."""
    validate_url(url)
    parsed = urlparse(url)
    host = parsed.hostname
    assert host is not None
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in
                         socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                            type=socket.SOCK_STREAM)]
        except (socket.gaierror, OSError, ValueError) as error:
            raise ValueError("URL hostname could not be resolved safely") from error
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        raise ValueError("URL hostname resolves to a non-public address")
    target = str(httpx.URL(url).copy_with(host=str(addresses[0])))
    extensions = {"sni_hostname": host} if parsed.scheme == "https" else {}
    return target, {"Host": parsed.netloc}, extensions


def _origin(url: str) -> tuple[str, str | None, int]:
    parsed = urlparse(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _redirect_headers(headers: dict, current: str, target: str) -> dict:
    if _origin(current) == _origin(target):
        return headers
    # Header names added by a future provider must not carry credentials to an
    # unrelated redirect target merely because this denylist did not know them.
    public = {"accept", "accept-language", "user-agent"}
    return {name: value for name, value in headers.items() if name.lower() in public}


async def safe_get(
    url: str,
    *,
    timeout: float = 15.0,
    max_redirects: int = _MAX_REDIRECTS,
    headers: Optional[dict] = None,
) -> httpx.Response:
    """HTTP GET with SSRF protection on every redirect hop."""
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        current = url
        forwarded = {name: value for name, value in (headers or {}).items() if name.lower() != "host"}
        for _ in range(max_redirects + 1):
            target, host_headers, extensions = _pinned_target(current)
            resp = await client.get(target, headers={**forwarded, **host_headers}, extensions=extensions)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return resp
                next_url = urljoin(current, location)
                if _origin(current) != _origin(next_url):
                    client.cookies.clear()
                forwarded = _redirect_headers(forwarded, current, next_url)
                current = next_url
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
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        current = url
        forwarded = {name: value for name, value in (headers or {}).items() if name.lower() != "host"}
        method, payload = "POST", data
        for _ in range(max_redirects + 1):
            target, host_headers, extensions = _pinned_target(current)
            resp = await client.request(method, target, data=payload,
                                        headers={**forwarded, **host_headers}, extensions=extensions)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return resp
                next_url = urljoin(current, location)
                if resp.status_code in (301, 302, 303):
                    method, payload = "GET", None
                elif _origin(current) != _origin(next_url):
                    raise ValueError("Refusing to forward POST data to another origin")
                if _origin(current) != _origin(next_url):
                    client.cookies.clear()
                forwarded = _redirect_headers(forwarded, current, next_url)
                current = next_url
                continue
            return resp
        raise ValueError(f"Too many redirects (max {max_redirects})")
