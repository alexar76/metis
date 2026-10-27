"""MCP stdio and Streamable HTTP client (JSON-RPC 2.0), without an SDK dependency."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from metis import __version__
from metis.mcp.config import MCPServerConfig, MCPTransport
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event
from metis.security.ssrf import _pinned_target


class MCPConnectionError(RuntimeError):
    pass


@dataclass
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """Connect to an MCP server and list/call tools."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._initialized = False
        self._http: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        if self.config.transport == MCPTransport.SSE:
            raise MCPConnectionError(
                f"SSE transport for '{self.config.name}' requires optional mcp SDK; use stdio"
            )
        if self.config.transport == MCPTransport.STREAMABLE_HTTP:
            if not self.config.url or not self.config.url.startswith(("https://", "http://")):
                raise MCPConnectionError("Streamable HTTP requires an http(s) endpoint")
            self._http = httpx.AsyncClient(
                timeout=30, headers={"Accept": "application/json, text/event-stream"}
            )
            try:
                await self._initialize()
            except BaseException:
                await self.close()
                raise
            return
        if not self.config.command:
            raise MCPConnectionError(f"MCP server '{self.config.name}' missing command")

        # SECURITY: pass only PATH + explicit config.env — never leak the full
        # os.environ (which contains METIS_API_KEY, cloud credentials, etc.).
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        env.update(self.config.env)
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await self._initialize()

    async def close(self) -> None:
        if self._http:
            if "Mcp-Session-Id" in self._http.headers:
                with suppress(httpx.HTTPError, ValueError):
                    target, headers, extensions = _pinned_target(self.config.url)
                    await self._http.delete(target, headers=headers, extensions=extensions)
            await self._http.aclose()
            self._http = None
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None
        self._initialized = False

    async def list_tools(self) -> List[MCPToolDescriptor]:
        if not self._initialized:
            await self.connect()
        tools, cursors, params = [], set(), {}
        for _ in range(64):
            result = await self._request("tools/list", params)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
            if cursor in cursors:
                raise MCPConnectionError("Repeated MCP tools/list cursor")
            cursors.add(cursor)
            params = {"cursor": cursor}
        else:
            raise MCPConnectionError("Too many MCP tools/list pages")
        prefix = self.config.tool_prefix
        out: List[MCPToolDescriptor] = []
        for t in tools:
            name = t.get("name", "")
            if prefix:
                name = f"{prefix}__{name}"
            out.append(
                MCPToolDescriptor(
                    name=name,
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
            )
        return out

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if not self._initialized:
            await self.connect()
        # Strip prefix for actual MCP call
        actual_name = name
        if self.config.tool_prefix and name.startswith(f"{self.config.tool_prefix}__"):
            actual_name = name[len(self.config.tool_prefix) + 2 :]
        emit_pipeline_event(
            PipelineEventKind.MCP_CALL,
            {"server": self.config.name, "tool": name},
        )
        result = await self._request("tools/call", {"name": actual_name, "arguments": arguments})
        content = result.get("content", [])
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) or json.dumps(result)

    async def _initialize(self) -> None:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "metis", "version": __version__},
            },
        )
        if self._http:
            version = result.get("protocolVersion")
            if version not in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}:
                raise MCPConnectionError("Unsupported negotiated MCP version")
            self._http.headers["MCP-Protocol-Version"] = version
        await self._notify("notifications/initialized", {})
        self._initialized = True

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._http:
            self._request_id += 1
            message = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
            response = await self._http_message(message)
            if "error" in response:
                raise MCPConnectionError(f"MCP error: {response['error']}")
            return response.get("result", {})
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise MCPConnectionError("MCP process not running")
        self._request_id += 1
        msg = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                stderr = ""
                if self._proc.stderr:
                    stderr = (await self._proc.stderr.read()).decode()[:500]
                raise MCPConnectionError(f"MCP server closed connection. stderr: {stderr}")
            try:
                resp = json.loads(raw.decode())
            except json.JSONDecodeError:
                continue
            if resp.get("id") != self._request_id:
                continue  # skip notifications
            if "error" in resp:
                raise MCPConnectionError(f"MCP error: {resp['error']}")
            return resp.get("result", {})

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        if self._http:
            await self._http_message({"jsonrpc": "2.0", "method": method, "params": params})
            return
        if not self._proc or not self._proc.stdin:
            raise MCPConnectionError("MCP process not running")
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()

    async def _http_message(self, message: dict) -> dict:
        try:
            return await self._http_exchange(message)
        except (httpx.HTTPError, ValueError) as exc:
            raise MCPConnectionError(f"MCP HTTP exchange failed ({type(exc).__name__})") from exc

    async def _http_exchange(self, message: dict) -> dict:
        target, headers, extensions = _pinned_target(self.config.url)
        async with self._http.stream("POST", target, headers=headers, extensions=extensions, json=message) as response:
            if response.status_code >= 400:
                raise MCPConnectionError(f"MCP HTTP {response.status_code}")
            if session := response.headers.get("mcp-session-id"):
                self._http.headers["Mcp-Session-Id"] = session
            if "id" not in message:
                if response.status_code != 202:
                    raise MCPConnectionError("MCP notification was not accepted")
                return {}
            if "text/event-stream" in response.headers.get("content-type", ""):
                data, size = [], 0
                async for line in response.aiter_lines():
                    size += len(line)
                    if size > 2_000_000:
                        raise MCPConnectionError("MCP response too large")
                    if not line and data:
                        reply = json.loads("\n".join(data))
                        data = []
                        if reply.get("id") == message["id"]:
                            return reply
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                raise MCPConnectionError("MCP stream ended without a matching reply")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise MCPConnectionError("MCP response too large")
            reply = json.loads(body)
            if reply.get("id") != message["id"]:
                raise MCPConnectionError("MCP response id mismatch")
            return reply
