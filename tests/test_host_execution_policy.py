"""A Python screen cannot grant public callers host execution authority."""
import asyncio

import httpx
import pytest

from metis.security.code_execution import DenyPublicHostExecution
from metis.tools.registry import CodeInterpreterTool
from metis.tools.sandbox import execute_sandboxed

pytestmark = pytest.mark.usefixtures("local_http_opt_in")


@pytest.fixture(autouse=True)
def no_process_starts(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("denied host execution must not start a process")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)


@pytest.mark.asyncio
async def test_host_execution_is_disabled_without_explicit_local_opt_in(monkeypatch):
    monkeypatch.delenv("METIS_UNSAFE_LOCAL_CODE", raising=False)
    result = await CodeInterpreterTool().run("print(1)")
    assert not result.success and "disabled" in result.error
    assert execute_sandboxed("print(1)")[0] is False


@pytest.mark.asyncio
async def test_production_refuses_even_when_local_opt_in_is_set(monkeypatch):
    monkeypatch.setenv("METIS_UNSAFE_LOCAL_CODE", "1")
    result = await CodeInterpreterTool(production=True).run("print(1)")
    assert not result.success
    monkeypatch.setenv("METIS_PRODUCTION", "true")
    assert execute_sandboxed("print(1)")[0] is False


@pytest.mark.asyncio
async def test_public_requests_cannot_use_private_opt_in_in_a_stream_or_task(monkeypatch):
    from fastapi import FastAPI
    from starlette.responses import StreamingResponse

    monkeypatch.setenv("METIS_UNSAFE_LOCAL_CODE", "1")
    monkeypatch.delenv("METIS_PRODUCTION", raising=False)
    app = FastAPI()
    app.add_middleware(DenyPublicHostExecution)

    @app.get("/probe")
    async def probe():
        async def response():
            result = await asyncio.create_task(CodeInterpreterTool().run("print(1)"))
            assert execute_sandboxed("print(1)")[0] is False
            yield "denied" if not result.success else "executed"

        return StreamingResponse(response())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        result = await client.get("/probe")
    assert result.text == "denied"


def test_private_import_escape_is_screened_even_in_trusted_development(monkeypatch):
    monkeypatch.setenv("METIS_UNSAFE_LOCAL_CODE", "1")
    monkeypatch.delenv("METIS_PRODUCTION", raising=False)
    # Previously reached sys.modules and arbitrary FileIO despite the source screen.
    code = 'from collections import _sys as runtime\nprint(runtime.modules["io"])'
    ok, _, error = execute_sandboxed(code)
    assert not ok and "private imports" in error
