"""Ecosystem MCP server presets for alexar76 projects."""

from __future__ import annotations

from typing import List

from metis.mcp.config import MCPServerConfig

ECOSYSTEM_MCP_CATALOG = {
    "aimarket-oracle-gateway": {
        "repo": "https://github.com/alexar76/aimarket-oracle-gateway",
        "description": "35 pay-per-call verifiable oracle tools (Platon, Chronos, LUMEN, …)",
        "glama": "https://glama.ai/mcp/servers/alexar76/aimarket-oracle-gateway",
        "tools_count": 35,
    },
    "aimarket-plugins": {
        "repo": "https://github.com/alexar76/aimarket-plugins",
        "description": "MCP Packager — generate a capability relay, Dockerfile and client config",
        "glama": "https://glama.ai/mcp/servers/alexar76/aimarket-plugins",
        "tools_count": 3,
    },
    "aimarket-web": {
        "repo": "https://github.com/alexar76/aimarket-mcp",
        "description": "Hosted AIMarket Hub — discover and invoke ecosystem capabilities",
        "glama": "https://glama.ai/mcp/servers/alexar76/aimarket-mcp",
        "tools_count": 13,
    },
}


def ecosystem_presets(names: List[str] | None = None) -> List[MCPServerConfig]:
    """Resolve ecosystem preset names to MCPServerConfig entries."""
    keys = names or list(ECOSYSTEM_MCP_CATALOG)
    return [MCPServerConfig.from_ecosystem_preset(k) for k in keys if k in ECOSYSTEM_MCP_CATALOG]


def default_ecosystem_mcp_config() -> List[MCPServerConfig]:
    """Recommended starter: oracle gateway (free list_oracle_capabilities, paid calls)."""
    return [MCPServerConfig.from_ecosystem_preset("aimarket-oracle-gateway")]
