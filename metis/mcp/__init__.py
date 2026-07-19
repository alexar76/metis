"""MCP client integration — load tools from ecosystem MCP servers."""

from metis.mcp.client import MCPClient, MCPConnectionError
from metis.mcp.config import MCPServerConfig

__all__ = [
    "MCPClient",
    "MCPConnectionError",
    "MCPServerConfig",
    "load_mcp_tools",
]


def load_mcp_tools(*args, **kwargs):
    from metis.mcp.registry import load_mcp_tools as _load

    return _load(*args, **kwargs)
