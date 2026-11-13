"""Tavily works through the existing METIS web_search tool."""

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from metis.config import RuntimeConfig
from metis.exoskeleton import Metis
from metis.observability.provider_events import TavilyActivityReporter
from metis.tools import registry


def configured_tool(monkeypatch, api_key=None):
    monkeypatch.setenv("METIS_WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("METIS_WEB_SEARCH_URL", "https://93.184.216.34/html/")
    if api_key:
        monkeypatch.setenv("METIS_TAVILY_API_KEY", api_key)
    else:
        monkeypatch.delenv("METIS_TAVILY_API_KEY", raising=False)
    config = RuntimeConfig(_env_file=None)
    exoskeleton = object.__new__(Metis)
    exoskeleton.config = config
    return exoskeleton._build_builtin_tools()


@pytest.mark.asyncio
async def test_keyless_search_returns_cited_sources(monkeypatch):
    tools = configured_tool(monkeypatch)
    request = httpx.Request("POST", "https://api.tavily.com/search")
    post = AsyncMock(return_value=httpx.Response(200, request=request, json={
        "results": [
            {"url": "https://modelcontextprotocol.io/specification", "title": "MCP specification", "content": "Tools."},
            {"url": "javascript:alert(1)", "title": "Injected link", "content": "Ignore this."},
        ],
    }))
    monkeypatch.setattr(registry, "safe_post", post)

    result = await tools.execute("web_search", " MCP tool discovery ")

    assert result.success
    assert "MCP specification" in result.output
    assert "https://modelcontextprotocol.io/specification" in result.output
    assert "Injected link" not in result.output
    post.assert_awaited_once_with(
        "https://api.tavily.com/search",
        headers={"X-Tavily-Access-Mode": "keyless"},
        max_redirects=0,
        json_body={"query": "MCP tool discovery", "max_results": 5, "include_answer": False},
    )


@pytest.mark.asyncio
async def test_keyless_quota_and_keyed_error_are_actionable_without_raw_body(monkeypatch):
    request = httpx.Request("POST", "https://api.tavily.com/search")
    post = AsyncMock(return_value=httpx.Response(429, request=request, text="Sensitive response details"))
    monkeypatch.setattr(registry, "safe_post", post)

    keyless = configured_tool(monkeypatch)
    result = await keyless.execute("web_search", "Example")
    assert not result.success and "METIS_TAVILY_API_KEY" in result.error
    assert "Sensitive response details" not in result.error

    keyed = configured_tool(monkeypatch, "test-tavily-key")
    result = await keyed.execute("web_search", "Example")
    assert not result.success and "HTTP 429" in result.error
    assert "test-tavily-key" not in result.error
    assert post.await_args.kwargs["headers"] == {"Authorization": "Bearer test-tavily-key"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_keyless_search_uses_duckduckgo_on_temporary_failure(monkeypatch, status):
    tools = configured_tool(monkeypatch)
    fallback_url = "https://93.184.216.34/html/"
    post = AsyncMock(side_effect=[
        httpx.Response(status, request=httpx.Request("POST", "https://api.tavily.com/search")),
        httpx.Response(200, request=httpx.Request("POST", fallback_url),
                       text='<a class="result__snippet">A fallback result</a>'),
    ])
    monkeypatch.setattr(registry, "safe_post", post)

    result = await tools.execute("web_search", "Example")

    assert result.success and "DuckDuckGo" in result.output and "A fallback result" in result.output
    assert post.await_args.args == (fallback_url,)
    assert post.await_args.kwargs["headers"] == {"User-Agent": "metis/0.1"}


@pytest.mark.asyncio
async def test_monitor_reports_tavily_outcome_without_search_content(monkeypatch):
    monkeypatch.setenv("ALIEN_MONITOR_URL", "https://monitor.modelmarket.dev/")
    monkeypatch.setenv("ALIEN_PROVIDER_EVENTS_TOKEN", "scoped-monitor-token")
    monkeypatch.setenv("ALIEN_API_TOKEN", "broad-monitor-token")
    events = []

    async def capture_event(request):
        events.append(request)
        return httpx.Response(204)

    real_client = httpx.AsyncClient

    def test_client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(capture_event), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", test_client)
    post = AsyncMock(side_effect=[
        httpx.Response(200, request=httpx.Request("POST", registry.TavilySearchTool.url),
                       json={"results": []}),
        httpx.Response(429, request=httpx.Request("POST", registry.TavilySearchTool.url)),
        httpx.Response(200, request=httpx.Request("POST", "https://93.184.216.34/html/"),
                       text='<a class="result__snippet">A fallback result</a>'),
    ])
    monkeypatch.setattr(registry, "safe_post", post)
    tools = configured_tool(monkeypatch)
    assert not (await tools.execute("web_search", " ")).success
    assert (await tools.execute("web_search", "private query")).success
    assert "DuckDuckGo" in (await tools.execute("web_search", "private fallback query")).output

    await asyncio.sleep(0)
    assert len(events) == 2
    for request, expected in zip(events, ("succeeded", "failed")):
        assert str(request.url) == "https://monitor.modelmarket.dev/api/provider-events"
        assert request.headers["Authorization"] == "Bearer scoped-monitor-token"
        body = json.loads(request.content)
        assert UUID(body.pop("event_id")).version == 4
        assert body == {"provider": "tavily", "source": "metis", "operation": "search", "status": expected}


def test_monitor_rejects_plain_http_external_target(monkeypatch):
    monkeypatch.setenv("ALIEN_MONITOR_URL", "http://monitor.modelmarket.dev")
    monkeypatch.setenv("ALIEN_PROVIDER_EVENTS_TOKEN", "scoped-monitor-token")
    assert TavilyActivityReporter.from_env() is None
