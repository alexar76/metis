"""Security-focused tests."""

from __future__ import annotations

import time

import pytest

from metis.distributed.security import verify_request_signature
from metis.security import validate_public_http_url
from metis.tools.registry import CodeInterpreterTool, WebSearchTool
import asyncio
import os
import subprocess

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
    # --- concatenation-built escapes found in the 2026-09 re-audit -----------------
    # Each defeats BOTH screen layers: the AST never sees a dunder Attribute node, and the
    # lowercased substring denylist never sees a whole dunder because it is split across
    # string fragments. All three were executed against the real sandbox before this landed.
    "operator_attrgetter_rce": (
        "import operator as o\n"
        "subs = o.attrgetter('__cl'+'ass__.'+'__ba'+'se__.'+'__subcl'+'asses__')(())()\n"
        "print(len(subs))"
    ),
    "str_format_getattr": (
        "field = '{0.'+'__cl'+'ass__.'+'__ba'+'se__.'+'__subcl'+'asses__}'\n"
        "print(field.format(()))"
    ),
    "io_fileio_read": (
        "import io\n"
        "print(io.FileIO('/etc/passwd','r').read()[:4])"
    ),
}


@pytest.mark.parametrize("name,code", list(_SANDBOX_ESCAPES.items()))
def test_sandbox_escape_blocked(name, code):
    ok, out, err = execute_sandboxed(code)
    assert ok is False, f"{name} was NOT blocked: out={out!r}"
    assert "Error" in err


def test_sandbox_allows_legit_compute():
    ok, out, err = execute_sandboxed("import math\nprint(math.sqrt(16) + sum(range(5)))")
    assert ok is True and out.strip() == "14.0", (out, err)


# --- 2026-09 re-audit: containment, because the screen is not a boundary -------------
#
# Three escapes past _screen_code() were executed against the real sandbox (operator
# .attrgetter, str.format field access, io.FileIO). All three are blocked above now, but the
# CLASS is not closed: any allowlisted primitive that resolves a runtime-built string into an
# attribute, import or file handle defeats a scan of the source. So what these tests pin is
# the layer that holds when the screen does not.

def test_scrub_child_env_drops_credentials_and_keeps_what_python_needs():
    from metis.security.child_env import scrub_child_env

    source = {
        "ANTHROPIC_API_KEY": "sk-secret",
        "OPENROUTER_API_KEY": "or-secret",
        "METIS_SIGNING_SEED_B64": "seed",
        "ORACLE_SIGNING_SEED_B64": "seed",
        "METIS_ADMIN_TOKEN": "tok",
        "AIMARKET_HUB_TOKEN": "tok",
        "DATABASE_URL": "postgres://u:p@h/db",
        "DOCKER_HOST": "tcp://127.0.0.1:2375",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
        "AWS_SECRET_ACCESS_KEY": "aws",
        "PATH": "/usr/bin",
        "PYTHONPATH": "/srv/metis",
        "HOME": "/home/metis",
        "LANG": "C.UTF-8",
    }
    scrubbed = scrub_child_env(source)

    for leaked in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "METIS_SIGNING_SEED_B64",
                   "ORACLE_SIGNING_SEED_B64", "METIS_ADMIN_TOKEN", "AIMARKET_HUB_TOKEN",
                   "DATABASE_URL", "DOCKER_HOST", "SSH_AUTH_SOCK", "AWS_SECRET_ACCESS_KEY"):
        assert leaked not in scrubbed, f"{leaked} reached untrusted code"
    # ...and the child must still be able to start and import METIS.
    for needed in ("PATH", "PYTHONPATH", "HOME", "LANG"):
        assert scrubbed[needed] == source[needed]


def test_scrub_child_env_denies_unknown_secrets_by_default():
    """A credential added to the deployment next month must be dropped without a code edit."""
    from metis.security.child_env import scrub_child_env

    invented = {
        "SOME_FUTURE_PROVIDER_API_KEY": "x",
        "BRAND_NEW_SERVICE_TOKEN": "x",
        "WHATEVER_PRIVATE_KEY": "x",
        "NEW_SIGNING_SEED": "x",
    }
    assert scrub_child_env(invented) == {}


@pytest.mark.asyncio
async def test_code_interpreter_child_gets_no_credentials(monkeypatch):
    """The wiring, not just the helper: capture the env actually handed to the subprocess."""
    from metis.tools.registry import CodeInterpreterTool

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-travel")
    monkeypatch.setenv("METIS_SIGNING_SEED_B64", "seed-must-not-travel")
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")

    captured = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    result = await CodeInterpreterTool(timeout=20).run("print(1 + 1)")
    assert result.success is True and result.output.strip() == "2", (result.output, result.error)

    env = captured["env"]
    assert env is not None, "the child still inherits os.environ wholesale"
    assert "ANTHROPIC_API_KEY" not in env
    assert "METIS_SIGNING_SEED_B64" not in env
    assert "DOCKER_HOST" not in env
    # The child has to remain able to import metis, or the sandbox silently stops running at
    # all — which is how an over-tight isolation flag turns into an outage rather than a fix.
    assert env.get("PYTHONPATH"), "the child cannot resolve `metis` without an import path"
    assert captured["cwd"] and captured["cwd"] != os.getcwd()


@pytest.mark.asyncio
async def test_code_interpreter_kills_the_child_on_timeout():
    """communicate() timing out leaves the process alive; a spinning payload must not leak one."""
    from metis.tools.registry import CodeInterpreterTool

    spinner = "while True:\n    pass"
    tool = CodeInterpreterTool(timeout=2)
    result = await tool.run(spinner)
    assert result.success is False
    assert "Timeout" in result.error
    # If the child were merely abandoned it would still be burning a core here.
    await asyncio.sleep(0.2)
    leaked = subprocess.run(
        ["pgrep", "-f", "metis.tools.sandbox"], capture_output=True, text=True
    )
    assert leaked.stdout.strip() == "", f"leaked sandbox pids: {leaked.stdout!r}"
