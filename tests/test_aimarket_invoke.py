"""AIMarket paid-invoke tool — tested against a REAL local HTTP hub (no mocks)."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.config import ProviderKind, RuntimeConfig
from metis.exoskeleton import Metis
from metis.tools.aimarket import AIMarketInvokeTool

_received: dict = {}


class _HubHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _received["body"] = body
        _received["channel"] = self.headers.get("X-Payment-Channel")
        if body.get("capability_id") == "fail.pay@v1":
            self.send_response(402)
            self.end_headers()
            self.wfile.write(b'{"error":"payment_required"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "result": {"echo": body.get("input"), "cap": body.get("capability_id")}
        }).encode())


@pytest.fixture(scope="module")
def hub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _HubHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def tool(hub):
    return AIMarketInvokeTool(hub, channel="ch_test", allow_local=True, timeout=5.0)


async def test_paid_invoke_success(tool):
    r = await tool.run('{"capability_id":"echo.tool@v1","product_id":"demo","input":{"q":"hi"}}')
    assert r.success, r.error
    assert "echo.tool@v1" in r.output
    assert _received["body"]["capability_id"] == "echo.tool@v1"
    assert _received["body"]["product_id"] == "demo"
    assert _received["channel"] == "ch_test"          # payment channel forwarded


async def test_bare_capability_id(tool):
    r = await tool.run("echo.tool@v1")
    assert r.success
    assert _received["body"]["product_id"] == "echo.tool"  # derived from cap id


async def test_missing_capability(tool):
    r = await tool.run("{}")
    assert not r.success and "capability_id" in r.error


async def test_bad_json(tool):
    r = await tool.run("{not json")
    assert not r.success


async def test_payment_required_402(tool):
    r = await tool.run('{"capability_id":"fail.pay@v1"}')
    assert not r.success and "402" in r.error


async def test_ssrf_blocks_private_host_without_dev_flag():
    t = AIMarketInvokeTool("http://127.0.0.1:9", allow_local=False)
    r = await t.run('{"capability_id":"x@v1"}')
    assert not r.success and "blocked" in r.error   # never even dials the socket


async def test_hub_unreachable_is_failsafe():
    t = AIMarketInvokeTool("http://127.0.0.1:9", allow_local=True, timeout=2.0)
    r = await t.run('{"capability_id":"x@v1"}')
    assert not r.success and "unreachable" in r.error


def test_registered_in_exoskeleton_when_enabled(tmp_path, hub):
    cfg = RuntimeConfig(provider=ProviderKind.MOCK, allow_test_provider=True,
                        memory_dir=tmp_path / "m", enable_ecosystem_invoke=True)
    cfg.economy.aimarket_hub_url = hub
    brain = Metis(cfg)
    assert "aimarket_invoke" in brain.tools.names()


def test_not_registered_by_default(tmp_path):
    cfg = RuntimeConfig(provider=ProviderKind.MOCK, allow_test_provider=True,
                        memory_dir=tmp_path / "m")
    brain = Metis(cfg)
    assert "aimarket_invoke" not in brain.tools.names()
