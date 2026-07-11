"""Security helpers: auth headers, HMAC signing, TLS config, audit logging."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("metis.distributed.audit")


@dataclass
class SecuritySettings:
    tls_verify: bool = True
    request_signing: bool = False
    hmac_secret_env: Optional[str] = None
    audit_log_prompts: bool = False

    def hmac_secret(self) -> Optional[str]:
        if not self.hmac_secret_env:
            return None
        return os.environ.get(self.hmac_secret_env)


def resolve_api_key(api_key_env: Optional[str], fallback: str = "") -> str:
    """Load API key from environment variable only — never from config plaintext."""
    if api_key_env:
        key = os.environ.get(api_key_env)
        if key:
            return key
    return fallback


def build_auth_headers(
    api_key: str,
    *,
    body: bytes = b"",
    security: Optional[SecuritySettings] = None,
) -> Dict[str, str]:
    """Build Bearer auth and optional HMAC-SHA256 request signing headers."""
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if security and security.request_signing:
        secret = security.hmac_secret()
        if secret:
            timestamp = str(int(time.time()))
            payload = f"{timestamp}.".encode("utf-8") + body
            signature = hmac.new(
                secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
            headers["X-Metis-Timestamp"] = timestamp
            headers["X-Metis-Signature"] = signature
    return headers


def verify_request_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
    *,
    max_age_seconds: int = 300,
) -> bool:
    """Verify HMAC signature and timestamp freshness."""
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age_seconds:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def httpx_verify_setting(security: Optional[SecuritySettings]) -> bool:
    """Return httpx verify flag from security settings."""
    if security is None:
        return True
    return security.tls_verify


def audit_cross_node_call(
    *,
    source: str,
    target_node: str,
    model: str,
    request_id: Optional[str] = None,
    status: str = "ok",
    latency_ms: Optional[float] = None,
    error: Optional[str] = None,
    message_count: int = 0,
) -> None:
    """Structured audit log — no prompt content by default."""
    entry: Dict[str, Any] = {
        "event": "cross_node_call",
        "source": source,
        "target_node": target_node,
        "model": model,
        "status": status,
        "message_count": message_count,
    }
    if request_id:
        entry["request_id"] = request_id
    if latency_ms is not None:
        entry["latency_ms"] = round(latency_ms, 2)
    if error:
        entry["error"] = error
    logger.info(json.dumps(entry, ensure_ascii=False))
