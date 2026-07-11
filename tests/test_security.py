"""Security-focused tests."""

from __future__ import annotations

import time

import pytest

from metis.distributed.security import verify_request_signature
from metis.security import validate_public_http_url
from metis.tools.registry import CodeInterpreterTool, WebSearchTool
from metis.tools.sandbox import execute_sandboxed


def test_hmac_replay_rejected():
    secret = "test-secret"
    body = b'{"model":"test"}'
    old_ts = str(int(time.time()) - 600)
    sig = __import__("hmac").new(
        secret.encode(),
        f"{old_ts}.".encode() + body,
        __import__("hashlib").sha256,
    ).hexdigest()
    assert not verify_request_signature(body, old_ts, sig, secret, max_age_seconds=300)


def test_hmac_fresh_request_accepted():
    secret = "test-secret"
    body = b'{"model":"test"}'
    ts = str(int(time.time()))
    sig = __import__("hmac").new(
        secret.encode(),
        f"{ts}.".encode() + body,
        __import__("hashlib").sha256,
    ).hexdigest()
    assert verify_request_signature(body, ts, sig, secret)


def test_ssrf_blocks_localhost():
    with pytest.raises(ValueError, match="not allowed"):
        validate_public_http_url("http://localhost/search")


def test_ssrf_blocks_private_ip():
    with pytest.raises(ValueError, match="private"):
        validate_public_http_url("http://192.168.1.1/search")


def test_ssrf_allows_public_url():
    url = validate_public_http_url("https://html.duckduckgo.com/html/")
    assert url.startswith("https://")


def test_web_search_rejects_private_url():
    with pytest.raises(ValueError):
        WebSearchTool(search_url="http://127.0.0.1/search")


@pytest.mark.asyncio
async def test_sandbox_blocks_os_import():
    ok, out, err = execute_sandboxed("import os\nprint(os.getcwd())")
    assert not ok
    assert "ImportError" in err or "not allowed" in err


@pytest.mark.asyncio
async def test_sandbox_allows_math():
    ok, out, err = execute_sandboxed("import math\nprint(math.sqrt(16))")
    assert ok
    assert "4.0" in out


@pytest.mark.asyncio
async def test_code_interpreter_sandboxed():
    tool = CodeInterpreterTool(timeout=5)
    result = await tool.run("print(2 + 2)")
    assert result.success
    assert "4" in result.output

    blocked = await tool.run("import os\nprint(os.listdir('.'))")
    assert not blocked.success


@pytest.mark.asyncio
async def test_code_interpreter_blocks_subprocess():
    tool = CodeInterpreterTool(timeout=5)
    result = await tool.run("import subprocess\nsubprocess.run(['echo','hi'])")
    assert not result.success


# --- C5 regression: sandbox escapes must stay blocked (frame-walk found in re-audit) ---

_SANDBOX_ESCAPES = {
    "frame_walk": (
        "try:\n raise ValueError()\n"
        "except Exception as e:\n"
        " g = e.__traceback__.tb_frame.f_back.f_globals\n"
        " g['sys'].modules['os'].system('echo pwned')"
    ),
    "format_string_dunder": 'print("{0.__class__}".format(""))',
    "subclasses_chain": "print(().__class__.__bases__[0].__subclasses__())",
    "generator_frame": "g = (x for x in [1])\nprint(g.gi_frame.f_globals)",
    "getattr_indirection": "print(getattr(1, 'real'))",
    "import_os": "import os\nprint(os.getcwd())",
}


@pytest.mark.parametrize("name,code", list(_SANDBOX_ESCAPES.items()))
def test_sandbox_escape_blocked(name, code):
    ok, out, err = execute_sandboxed(code)
    assert ok is False, f"{name} was NOT blocked: out={out!r}"
    assert "Error" in err


def test_sandbox_allows_legit_compute():
    ok, out, err = execute_sandboxed("import math\nprint(math.sqrt(16) + sum(range(5)))")
    assert ok is True and out.strip() == "14.0", (out, err)
