"""Token-bucket rate limiter for node server."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Tuple


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    burst: int = 10
    per_api_key: bool = True


@dataclass
class _Bucket:
    tokens: float
    last_update: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Per-IP and per-API-key token bucket rate limiter."""

    _SWEEP_INTERVAL = 60.0  # evict idle buckets at most once per minute

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._buckets: Dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(config.burst))
        )
        self._lock = Lock()
        self._last_sweep = time.monotonic()

    def allow(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, retry_after_seconds)."""
        with self._lock:
            now = time.monotonic()
            self._sweep_stale(now)  # bound memory: drop fully-refilled idle buckets
            bucket = self._buckets[key]
            # Clamp: a freshly-created bucket stamps last_update at creation, which
            # can be marginally after `now` — never let elapsed go negative.
            elapsed = max(0.0, now - bucket.last_update)
            refill_rate = self.config.requests_per_minute / 60.0
            bucket.tokens = min(
                float(self.config.burst),
                bucket.tokens + elapsed * refill_rate,
            )
            bucket.last_update = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0
            retry = int((1.0 - bucket.tokens) / refill_rate) + 1
            return False, retry

    def _sweep_stale(self, now: float) -> None:
        """Evict buckets idle long enough to have fully refilled — dropping such a
        bucket is behaviourally identical to keeping it (a fresh bucket starts full),
        so this bounds memory under a distinct-IP/key flood without changing limits.
        Called under the lock; runs at most once per _SWEEP_INTERVAL. O(n) only then.
        """
        if now - self._last_sweep < self._SWEEP_INTERVAL:
            return
        self._last_sweep = now
        refill_rate = max(self.config.requests_per_minute / 60.0, 1e-9)
        full_after = self.config.burst / refill_rate  # secs to refill 0 → burst
        ttl = max(120.0, full_after + 60.0)
        stale = [k for k, b in self._buckets.items() if now - b.last_update > ttl]
        for k in stale:
            del self._buckets[k]

    def client_key(self, ip: str, api_key: str = "") -> str:
        if self.config.per_api_key and api_key:
            return f"key:{api_key[:16]}"
        return f"ip:{ip}"
