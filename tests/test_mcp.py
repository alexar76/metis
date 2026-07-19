"""Tests for MCP tool loading (mocked)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from metis.mcp.client import MCPClient, MCPToolDescriptor
from metis.mcp.config import MCPServerConfig, MCPTransport
from metis.mcp.discovery import ECOSYSTEM_MCP_CATALOG, ecosystem_presets
from metis.mcp.registry import MCPTool, _parse_tool_input, load_mcp_tools
from metis.tools.registry import ToolRegistry


def test_ecosystem_presets_catalog():
    assert "aimarket-oracle-gateway" in ECOSYSTEM_MCP_CATALOG
    presets = ecosystem_presets(["aimarket-oracle-gateway"])
    assert len(presets) == 1
    assert presets[0].name == "aimarket-oracle-gateway"
    assert presets[0].tool_prefix == "oracle"


def test_parse_tool_input_json():
    args = _parse_tool_input('{"query": "test"}', {"properties": {"query": {}}})
    assert args == {"query": "test"}


def test_parse_tool_input_plain_text():
    args = _parse_tool_input("hello world", {"properties": {"query": {}}})
    assert args == {"query": "hello world"}


@pytest.mark.asyncio
async def test_mcp_tool_run():
    client = AsyncMock()
    client.call_tool = AsyncMock(return_value="oracle result")
    tool = MCPTool(client, "oracle__get_random", "Get random", {})
    result = await tool.run('{"bytes": 32}')
    assert result.success
    assert "oracle result" in result.output
    client.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_load_mcp_tools_mock():
    registry = ToolRegistry()
    cfg = MCPServerConfig(
        name="test-server",
        command="echo",
        args=[],
        tool_prefix="test",
    )

    mock_tools = [
        MCPToolDescriptor(name="test__tool_a", description="Tool A", input_schema={}),
        MCPToolDescriptor(name="test__tool_b", description="Tool B", input_schema={}),
    ]

    with patch.object(MCPClient, "connect", new_callable=AsyncMock), patch.object(
        MCPClient, "list_tools", new_callable=AsyncMock, return_value=mock_tools
    ):
        count = await load_mcp_tools([cfg], registry)
        assert count == 2
        assert "test__tool_a" in registry.names()
        assert "test__tool_b" in registry.names()


def test_mcp_server_config_from_preset():
    cfg = MCPServerConfig.from_ecosystem_preset("aimarket-oracle-gateway")
    assert cfg.transport == MCPTransport.STDIO
    assert "aimarket_oracle_gateway" in " ".join(cfg.args)
