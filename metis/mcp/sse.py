"""MCP SSE transport client."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from metis.mcp.client import MCPConnectionError, MCPToolDescriptor
from metis.mcp.config import MCPServerConfig
from metis.security.ssrf import validate_url


class MCPSSEClient:
    """MCP client over HTTP SSE transport."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        if not config.url:
            raise MCPConnectionError(f"SSE server '{config.name}' missing url")
        self._url = validate_url(config.url)
        self._client = httpx.AsyncClient(timeout=60.0, follow_redirects=False)
        self._request_id = 0
        self._session_id: Optional[str] = None

    async def connect(self) -> None:
        resp = await self._client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "metis", "version": "0.1.0"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        resp.raise_for_status()
        data = self._parse_response(resp.text)
        if "error" in data:
            raise MCPConnectionError(str(data["error"]))

    async def close(self) -> None:
        await self._client.aclose()

    async def list_tools(self) -> List[MCPToolDescriptor]:
        result = await self._request("tools/list", {})
        prefix = self.config.tool_prefix
        out: List[MCPToolDescriptor] = []
        for t in result.get("tools", []):
            name = t.get("name", "")
            if prefix:
                name = f"{prefix}__{name}"
            out.append(MCPToolDescriptor(name=name, description=t.get("description", ""), input_schema=t.get("inputSchema", {})))
        return out

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        actual = name
        if self.config.tool_prefix and name.startswith(f"{self.config.tool_prefix}__"):
            actual = name[len(self.config.tool_prefix) + 2:]
        result = await self._request("tools/call", {"name": actual, "arguments": arguments})
        parts = []
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts) or json.dumps(result)

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._request_id += 1
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        resp = await self._client.post(
            self._url,
            json={"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params},
            headers=headers,
        )
        resp.raise_for_status()
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        data = self._parse_response(resp.text)
        if "error" in data:
            raise MCPConnectionError(str(data["error"]))
        return data.get("result", {})

    @staticmethod
    def _parse_response(text: str) -> Dict[str, Any]:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
