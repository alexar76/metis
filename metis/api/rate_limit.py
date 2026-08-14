"""Simple in-memory per-key rate limiting for the OpenAI API."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import DefaultDict, Deque, Optional

from fastapi import HTTPException, Request


def _limit_per_minute() -> int:
    return int(os.environ.get("METIS_RATE_LIMIT_PER_MINUTE", "60"))


class RateLimiter:
    """Token-bucket style limiter keyed by API key or client IP."""

    def __init__(self, limit_per_minute: int = 60) -> None:
        self.limit = limit_per_minute
        self._windows: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._calls = 0

    def _key(self, request: Request, api_key: Optional[str]) -> str:
        if api_key:
            return f"key:{api_key}"
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"

    def check(self, request: Request, api_key: Optional[str]) -> None:
        key = self._key(request, api_key)
        now = time.monotonic()
        window: Deque[float] = self._windows[key]

        while window and now - window[0] > 60.0:
            window.popleft()

        if len(window) >= self.limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {self.limit} requests per minute",
            )

        window.append(now)
        self._evict_idle(now)

    def _evict_idle(self, now: float) -> None:
        """Drop fully drained windows so the dict stays bounded.

        This used to happen inline in check(): an empty window was deleted from the
        dict and then appended to, so the very next request re-created an empty one
        and the count never reached the limit. Evicting AFTER the append — and only
        keys other than the one just touched — keeps memory bounded and still counts.
        """
        self._calls += 1
        if self._calls % 1000:
            return
        for k in [k for k, w in self._windows.items() if not w or now - w[-1] > 60.0]:
            del self._windows[k]

    def reset(self) -> None:
        self._windows.clear()


_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(_limit_per_minute())
    return _limiter
