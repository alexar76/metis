"""Production security layer."""

from metis.security.injection import (
    build_system_prompt,
    sanitize_tool_output,
    sanitize_user_input,
    validate_message_roles,
    verify_canary_intact,
    wrap_untrusted,
)
from metis.security.ssrf import safe_get, safe_post, validate_url
from metis.security.ratelimit import RateLimitConfig, RateLimiter
from metis.security.audit import log_security_event

# Backward compat
validate_public_http_url = validate_url

__all__ = [
    "build_system_prompt",
    "sanitize_tool_output",
    "sanitize_user_input",
    "validate_message_roles",
    "verify_canary_intact",
    "wrap_untrusted",
    "safe_get",
    "safe_post",
    "validate_url",
    "validate_public_http_url",
    "RateLimitConfig",
    "RateLimiter",
    "log_security_event",
]
