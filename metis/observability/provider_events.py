"""Report the outcome of real Tavily calls to Alien Monitor."""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


def _endpoint(raw: str) -> str | None:
    try:
        parsed = urlsplit(raw.strip())
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            return None
        if parsed.query or parsed.fragment:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/api/provider-events", "", ""))
    except ValueError:
        return None


class TavilyActivityReporter:
    def __init__(self, endpoint: str, token: str):
        self._endpoint = endpoint
        self._token = token
        self._pending: set[asyncio.Task[None]] = set()

    @classmethod
    def from_env(cls) -> TavilyActivityReporter | None:
        endpoint = _endpoint(os.environ.get("ALIEN_MONITOR_URL") or os.environ.get("MONITOR_URL") or "")
        token = next((value for name in (
            "ALIEN_PROVIDER_EVENTS_TOKEN", "ALIEN_API_TOKEN", "ALIEN_MONITOR_API_TOKEN",
        ) if (value := os.environ.get(name, "").strip())), "")
        return cls(endpoint, token) if endpoint and token else None

    def __call__(self, succeeded: bool) -> None:
        if len(self._pending) >= 32:
            return
        task = asyncio.create_task(self._post(str(uuid4()), "succeeded" if succeeded else "failed"))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _post(self, event_id: str, status: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream(
                    "POST", self._endpoint, headers={"Authorization": f"Bearer {self._token}"},
                    json={"event_id": event_id, "provider": "tavily", "source": "metis",
                          "operation": "search", "status": status},
                ) as response:
                    if not response.is_success:
                        logger.debug("Monitor provider event: HTTP %s", response.status_code)
        except (httpx.HTTPError, ValueError):
            logger.debug("Monitor provider event: delivery unavailable")
