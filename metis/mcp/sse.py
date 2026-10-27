"""Compatibility name for the historical HTTP/SSE-response MCP client.

It posted JSON-RPC to one endpoint, rather than using the old GET /sse transport.
Share the Streamable HTTP implementation so session negotiation, notifications,
pagination and SSRF checks cannot diverge between the two configuration names.
"""
from metis.mcp.client import MCPClient
from metis.mcp.config import MCPServerConfig, MCPTransport


class MCPSSEClient(MCPClient):
    def __init__(self, config: MCPServerConfig):
        super().__init__(config.model_copy(update={"transport": MCPTransport.STREAMABLE_HTTP}))
