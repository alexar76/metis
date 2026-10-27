import json
import socket

import httpx
import pytest
from metis.mcp.client import MCPClient
from metis.mcp.config import MCPServerConfig, MCPTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("compat", [False, True])
async def test_http_negotiation_pagination_and_cleanup(monkeypatch, sse, compat):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    seen = []
    def handle(request):
        seen.append(request)
        if request.method == "DELETE":
            return httpx.Response(200)
        message = json.loads(request.content)
        if message["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        else:
            assert request.headers["mcp-session-id"] == "fixture-session"
            assert request.headers["mcp-protocol-version"] == "2025-06-18"
            if message["method"] == "notifications/initialized":
                return httpx.Response(202)
            assert message["method"] == "tools/list"
            page = bool(message["params"].get("cursor"))
            result = {"tools": [{"name": "second" if page else "first", "inputSchema": {"type": "object"}}]}
            if not page:
                result["nextCursor"] = "page2"
        reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        if sse:
            return httpx.Response(200, headers={"content-type": "text/event-stream", "mcp-session-id": "fixture-session"},
                                  text=': keepalive\n\nevent: message\ndata: ' + json.dumps(reply) + '\n\n')
        return httpx.Response(200, json=reply, headers={"mcp-session-id": "fixture-session"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    from metis.mcp.sse import MCPSSEClient
    client_type = MCPSSEClient if compat else MCPClient
    client = client_type(MCPServerConfig(name="fixture", transport=MCPTransport.STREAMABLE_HTTP,
                                        url="https://fixture.invalid/mcp", tool_prefix="hub"))
    try:
        assert [tool.name for tool in await client.list_tools()] == ["hub__first", "hub__second"]
    finally:
        await client.close()
    assert seen[-1].method == "DELETE"
    assert client._http is None
    assert all(request.url.host == "93.184.216.34" for request in seen)
    assert all(request.headers["host"] == "fixture.invalid" for request in seen)


def test_presets_use_shipped_modules_and_supported_transport():
    oracle = MCPServerConfig.from_ecosystem_preset("aimarket-oracle-gateway")
    packager = MCPServerConfig.from_ecosystem_preset("aimarket-plugins")
    web = MCPServerConfig.from_ecosystem_preset("aimarket-web")
    assert oracle.args == ["-m", "aimarket_oracle_gateway.stdio_server"]
    assert packager.args == ["-m", "aimarket_mcp_packager.stdio_server"]
    assert web.transport == MCPTransport.STREAMABLE_HTTP
