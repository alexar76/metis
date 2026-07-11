"""Per-endpoint circuit breaker."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict

from metis.observability.config import CircuitBreakerConfig
from metis.observability.reliability.detector import FailureKind


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    endpoint: str
    config: CircuitBreakerConfig
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    opened_at: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def before_call(self) -> None:
        if not self.config.enabled:
            return
        with self._lock:
            if self.state == BreakerState.OPEN:
                if time.monotonic() - self.opened_at >= self.config.recovery_seconds:
                    self.state = BreakerState.HALF_OPEN
                else:
                    raise RuntimeError(
                        f"Circuit breaker OPEN for {self.endpoint} "
                        f"(failures={self.failure_count})"
                    )

    def record_success(self) -> None:
        if not self.config.enabled:
            return
        with self._lock:
            self.failure_count = 0
            self.state = BreakerState.CLOSED

    def record_failure(self, kind: FailureKind) -> None:
        if not self.config.enabled:
            return
        if kind in (FailureKind.AUTH, FailureKind.VALIDATION):
            return
        with self._lock:
            self.failure_count += 1
            if self.failure_count >= self.config.failure_threshold:
                self.state = BreakerState.OPEN
                self.opened_at = time.monotonic()

    def status(self) -> Dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "enabled": self.config.enabled,
        }


_registry: Dict[str, CircuitBreaker] = {}
_registry_lock = Lock()


def get_breaker(endpoint: str, config: CircuitBreakerConfig) -> CircuitBreaker:
    with _registry_lock:
        if endpoint not in _registry:
            _registry[endpoint] = CircuitBreaker(endpoint=endpoint, config=config)
        return _registry[endpoint]


def all_breaker_status() -> list[Dict[str, object]]:
    with _registry_lock:
        return [b.status() for b in _registry.values()]


def reset_breakers() -> None:
    with _registry_lock:
        _registry.clear()
