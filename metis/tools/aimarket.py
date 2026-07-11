"""AIMarket paid-invoke tool — Metis pays to use other ecosystem capabilities.

Two ways to spend, "money everywhere":

* **MCP tools** (already wired via ``mcp_ecosystem_presets``) — the oracle gateway
  and plugins bill per call over MCP.
* **Direct hub invoke** (this tool) — the agent loop can call ANY capability
  registered in the AIMarket Hub by POSTing to ``{hub}/ai-market/v2/invoke`` with a
  payment channel; the hub debits the channel / escrow and returns the result.

It is opt-in (``enable_ecosystem_invoke`` + a configured hub URL) and offline-safe:
any failure returns a clean ``ToolResult`` error, never raises. Outbound URLs are
SSRF-validated (private hosts blocked unless ``METIS_ALLOW_LOCAL_INVOKE=1`` for dev).
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from metis.security import sanitize_tool_output
from metis.security.ssrf import validate_url
from metis.tools.registry import Tool, ToolResult


class AIMarketInvokeTool(Tool):
    name = "aimarket_invoke"
    description = (
        "Invoke a PAID capability from the AIMarket hub (pay-per-call). "
        'Input JSON: {"capability_id":"my.tool@v1","product_id":"...","input":{...}} '
        "— or just a bare capability id."
    )

    def __init__(
        self,
        hub_url: str,
        *,
        channel: Optional[str] = None,
        channel_secret: Optional[str] = None,
        source_hub: str = "local",
        timeout: float = 60.0,
        allow_local: bool = False,
    ) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.channel = channel
        self.channel_secret = channel_secret
        self.source_hub = source_hub
        self.timeout = timeout
        self.allow_local = allow_local

    def _parse(self, input_text: str) -> dict[str, Any]:
        s = (input_text or "").strip()
        if s.startswith("{"):
            return json.loads(s)  # may raise → handled by caller
        return {"capability_id": s}

    async def run(self, input_text: str) -> ToolResult:
        try:
            spec = self._parse(input_text)
        except (json.JSONDecodeError, ValueError):
            return ToolResult(self.name, False, "", "input must be JSON {capability_id, product_id?, input?}")

        cap = str(spec.get("capability_id") or "").strip()
        if not cap:
            return ToolResult(self.name, False, "", "capability_id is required")
        product = str(spec.get("product_id") or cap.split("@")[0]).strip()
        raw_input = spec.get("input")
        if not isinstance(raw_input, dict):
            raw_input = {"query": raw_input} if raw_input is not None else {}

        url = f"{self.hub_url}/ai-market/v2/invoke"
        if not self.allow_local:
            try:
                validate_url(url, allowed_schemes={"http", "https"})
            except ValueError as exc:
                return ToolResult(self.name, False, "", f"hub url blocked ({exc}); set METIS_ALLOW_LOCAL_INVOKE=1 for dev")

        payload = {
            "product_id": product,
            "capability_id": cap,
            "source_hub": self.source_hub,
            "input": raw_input,
        }
        headers = {"Content-Type": "application/json"}
        if self.channel:
            headers["X-Payment-Channel"] = self.channel
        if self.channel_secret:
            headers["X-Payment-Channel-Secret"] = self.channel_secret

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
        except Exception as exc:  # offline-safe
            return ToolResult(self.name, False, "", f"hub unreachable: {type(exc).__name__}")

        if r.status_code != 200:
            return ToolResult(self.name, False, "", f"hub returned {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except ValueError:
            return ToolResult(self.name, False, "", "hub returned non-JSON")
        result = data.get("result", data.get("output", data)) if isinstance(data, dict) else data
        out = json.dumps(result, ensure_ascii=False, default=str)[:8000]
        return ToolResult(self.name, True, sanitize_tool_output(out))
