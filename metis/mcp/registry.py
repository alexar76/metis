"""Bridge MCP tools into Metis ToolRegistry."""

from __future__ import annotations

import json
import logging
from typing import Any, List

from metis.mcp.client import MCPClient, MCPConnectionError
from metis.mcp.config import MCPServerConfig, MCPTransport
from metis.mcp.sse import MCPSSEClient
from metis.tools.registry import Tool, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


class MCPTool(Tool):
    """Wraps one MCP tool as a Metis Tool."""

    def __init__(self, client: MCPClient, name: str, description: str, input_schema: dict):
        self._client = client
        self.name = name
        self.description = description
        self._input_schema = input_schema

    async def run(self, input_text: str) -> ToolResult:
        try:
            args = _parse_tool_input(input_text, self._input_schema)
            output = await self._client.call_tool(self.name, args)
            # SECURITY: wrap MCP tool output as untrusted — external servers may
            # inject instructions into the LLM context.
            from metis.security import sanitize_tool_output
            return ToolResult(self.name, True, sanitize_tool_output(output[:8000]))
        except Exception as e:
            return ToolResult(self.name, False, "", str(e))


def _parse_tool_input(input_text: str, schema: dict) -> dict:
    """Parse tool input — JSON if possible, else wrap as query."""
    text = input_text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    props = schema.get("properties", {})
    if "query" in props:
        return {"query": text}
    if len(props) == 1:
        key = next(iter(props))
        return {key: text}
    return {"input": text}


async def load_mcp_tools(
    servers: List[MCPServerConfig],
    registry: ToolRegistry,
) -> int:
    loaded = 0
    for cfg in servers:
        if not cfg.enabled:
            continue
        if cfg.transport == MCPTransport.SSE:
            client: Any = MCPSSEClient(cfg)
        else:
            client = MCPClient(cfg)
        try:
            await client.connect()
            descriptors = await client.list_tools()
            for desc in descriptors:
                registry.register(MCPTool(client, desc.name, desc.description, desc.input_schema))
                loaded += 1
            logger.info("Loaded %d tools from MCP server '%s'", len(descriptors), cfg.name)
        except MCPConnectionError as e:
            logger.warning("MCP server '%s' unavailable: %s", cfg.name, e)
    return loaded
