"""Failure classification for retry and circuit-breaker decisions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx


class FailureKind(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    MODEL_ERROR = "model_error"
    AUTH = "auth"
    VALIDATION = "validation"
    PARSE_ERROR = "parse_error"
    INJECTION_BLOCKED = "injection_blocked"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


@dataclass
class FailureRecord:
    kind: FailureKind
    message: str
    retryable: bool
    status_code: Optional[int] = None
    endpoint: Optional[str] = None


_PATTERNS: list[tuple[FailureKind, re.Pattern[str], bool]] = [
    (FailureKind.TIMEOUT, re.compile(r"timeout|timed out|deadline", re.I), True),
    (FailureKind.RATE_LIMIT, re.compile(r"rate.?limit|429|too many requests", re.I), True),
    (FailureKind.NETWORK, re.compile(r"connection|network|dns|unreachable|refused", re.I), True),
    (FailureKind.AUTH, re.compile(r"401|403|unauthorized|forbidden|api.?key", re.I), False),
    (FailureKind.VALIDATION, re.compile(r"422|400|invalid|validation", re.I), False),
    (FailureKind.PARSE_ERROR, re.compile(r"json|parse|decode", re.I), False),
    (FailureKind.INJECTION_BLOCKED, re.compile(r"injection", re.I), False),
    (FailureKind.CIRCUIT_OPEN, re.compile(r"circuit breaker|circuit_open", re.I), False),
    (FailureKind.MODEL_ERROR, re.compile(r"500|502|503|504|overloaded|server error", re.I), True),
]


def classify_failure(
    exc: BaseException,
    *,
    status_code: Optional[int] = None,
    endpoint: Optional[str] = None,
) -> FailureRecord:
    msg = str(exc)

    if isinstance(exc, httpx.TimeoutException):
        return FailureRecord(FailureKind.TIMEOUT, msg, True, status_code, endpoint)

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code

    if status_code == 429:
        return FailureRecord(FailureKind.RATE_LIMIT, msg, True, status_code, endpoint)
    if status_code in (401, 403):
        return FailureRecord(FailureKind.AUTH, msg, False, status_code, endpoint)
    if status_code and status_code >= 500:
        return FailureRecord(FailureKind.MODEL_ERROR, msg, True, status_code, endpoint)

    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, ConnectionError, OSError)):
        return FailureRecord(FailureKind.NETWORK, msg, True, status_code, endpoint)

    if isinstance(exc, json.JSONDecodeError):
        return FailureRecord(FailureKind.PARSE_ERROR, msg, False, status_code, endpoint)

    for kind, pattern, retryable in _PATTERNS:
        if pattern.search(msg):
            return FailureRecord(kind, msg, retryable, status_code, endpoint)

    return FailureRecord(FailureKind.UNKNOWN, msg, False, status_code, endpoint)
