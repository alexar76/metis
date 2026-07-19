"""Exponential backoff retry policy with circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional, TypeVar

from metis.observability.config import ReliabilityConfig
from metis.observability.logging.tracer import endpoint_host, log_module_call
from metis.observability.reliability.detector import classify_failure

logger = logging.getLogger("metis.reliability")
T = TypeVar("T")


class RetryPolicy:
    def __init__(self, config: Optional[ReliabilityConfig] = None):
        self.config = config or ReliabilityConfig()

    def _delay_ms(self, attempt: int) -> float:
        base = self.config.base_delay_ms * (2 ** attempt)
        capped = min(base, self.config.max_delay_ms)
        jitter = random.uniform(0, capped * 0.25)
        return capped + jitter

    def is_retryable(self, record) -> bool:
        return record.kind.value in self.config.retryable_errors and record.retryable

    async def execute(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        endpoint: str = "",
        module_role: str = "unknown",
        idempotent: bool = True,
    ) -> T:
        if not idempotent:
            return await fn()
        return await with_retry(fn, policy=self, endpoint=endpoint or module_role, module_role=module_role)


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    endpoint: str = "default",
    module_role: str = "unknown",
) -> T:
    from metis.observability.reliability.circuit_breaker import get_breaker

    ep_host = endpoint_host(endpoint) if "://" in endpoint else endpoint
    breaker = get_breaker(ep_host, policy.config.circuit_breaker)
    last_exc: BaseException | None = None

    for attempt in range(policy.config.max_retries + 1):
        breaker.before_call()
        try:
            result = await fn()
            breaker.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            record = classify_failure(exc, endpoint=ep_host)
            breaker.record_failure(record.kind)
            if attempt >= policy.config.max_retries or not policy.is_retryable(record):
                raise
            delay = policy._delay_ms(attempt) / 1000.0
            log_module_call(
                module_role,
                latency_ms=0,
                status="retry",
                error_code=record.kind.value,
                endpoint=endpoint,
                extra={"attempt": attempt + 1, "delay_s": round(delay, 3)},
            )
            logger.warning(
                "retry attempt=%s endpoint=%s kind=%s delay=%.2fs",
                attempt + 1, ep_host, record.kind.value, delay,
            )
            await asyncio.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("with_retry exhausted without result")
