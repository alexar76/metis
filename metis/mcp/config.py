"""MCP server configuration."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPTransport(str, Enum):
    STDIO = "stdio"
    SSE = "sse"


class MCPServerConfig(BaseModel):
    """One MCP server entry from cluster/config YAML."""

    name: str
    transport: MCPTransport = MCPTransport.STDIO
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None  # SSE endpoint
    enabled: bool = True
    tool_prefix: Optional[str] = None  # namespace tools as prefix__toolname

    @classmethod
    def from_ecosystem_preset(cls, preset: str) -> MCPServerConfig:
        """Known alexar76 ecosystem MCP servers."""
        presets: Dict[str, Dict[str, Any]] = {
            "aimarket-oracle-gateway": {
                "name": "aimarket-oracle-gateway",
                "command": "python",
                "args": ["-m", "aimarket_oracle_gateway.mcp_stdio_server"],
                "env": {"AIMARKET_HUB_URL": "https://modelmarket.dev"},
                "tool_prefix": "oracle",
            },
            "aimarket-plugins": {
                "name": "aimarket-plugins",
                "command": "python",
                "args": ["-m", "aimarket_plugins.mcp_server"],
                "env": {"AIMARKET_HUB_URL": "https://modelmarket.dev"},
                "tool_prefix": "hub",
            },
            "aimarket-web": {
                "name": "aimarket-web",
                "transport": MCPTransport.SSE,
                "url": os.environ.get("AIMARKET_MCP_URL", "https://mcp.modelmarket.dev/mcp"),
                "tool_prefix": "web",
            },
        }
        if preset not in presets:
            raise ValueError(f"Unknown ecosystem preset: {preset}. Known: {list(presets)}")
        return cls(**presets[preset])
