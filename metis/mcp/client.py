"""Minimal MCP stdio client (JSON-RPC 2.0) — no full SDK required."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from metis.mcp.config import MCPServerConfig, MCPTransport
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event


class MCPConnectionError(RuntimeError):
    pass


@dataclass
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """Connect to an MCP server over stdio and list/call tools."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._initialized = False

    async def connect(self) -> None:
        if self.config.transport == MCPTransport.SSE:
            raise MCPConnectionError(
                f"SSE transport for '{self.config.name}' requires optional mcp SDK; use stdio"
            )
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
        result = await self._request("tools/list", {})
        tools = result.get("tools", [])
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
        await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "metis", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})
        self._initialized = True

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
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
        if not self._proc or not self._proc.stdin:
            raise MCPConnectionError("MCP process not running")
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()
