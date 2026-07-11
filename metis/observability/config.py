"""Observability and reliability configuration."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class LogContentMode(str, Enum):
    REDACTED = "redacted"
    FULL = "full"
    HASH = "hash"


class CircuitBreakerConfig(BaseModel):
    enabled: bool = True
    failure_threshold: int = 5
    recovery_seconds: int = 60


class ReliabilityConfig(BaseModel):
    max_retries: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 30000
    retryable_errors: List[str] = Field(
        default_factory=lambda: ["timeout", "rate_limit", "network", "model_error"]
    )
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)


class ObservabilityConfig(BaseModel):
    log_level: str = "INFO"
    log_format: str = "json"
    log_content: LogContentMode = LogContentMode.REDACTED
    log_file: Optional[str] = None
    audit_log_file: Optional[str] = None
    audit_hash_chain: bool = False
    trace_dir: Optional[str] = None
    reliability: ReliabilityConfig = Field(default_factory=ReliabilityConfig)
