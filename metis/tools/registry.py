"""Tool layer: code interpreter, web search, registry."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from metis.economy.meter import get_current_meter
from metis.models.provider import LLMProvider, extract_json
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event
from metis.security import sanitize_tool_output
from metis.security.ssrf import safe_post, validate_url


@dataclass
class ToolResult:
    name: str
    success: bool
    output: str
    error: str = ""


def _child_rlimits() -> None:
    """Best-effort POSIX resource limits for the sandbox child (runs in the forked child).

    Each limit is set independently and failures are swallowed: platforms differ on which
    RLIMIT_* they honour (macOS quietly ignores RLIMIT_AS), and a limit we cannot set must
    never stop the sandbox from running — it just means one layer fewer on that host. These
    bound a screen escape's blast radius (CPU burn, a multi-gigabyte allocation, writing a
    huge file); they are containment, not the boundary.
    """
    try:
        import resource
    except Exception:
        return
    for what, soft, hard in (
        (getattr(resource, "RLIMIT_CPU", None), 30, 30),               # seconds of CPU
        (getattr(resource, "RLIMIT_FSIZE", None), 16 << 20, 16 << 20),  # 16 MiB max write
        (getattr(resource, "RLIMIT_AS", None), 2048 << 20, 2048 << 20), # 2 GiB address space
    ):
        if what is None:
            continue
        try:
            resource.setrlimit(what, (soft, hard))
        except (ValueError, OSError):
            pass


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, input_text: str) -> ToolResult:
        ...


class CodeInterpreterTool(Tool):
    name = "code_interpreter"
    description = "Execute Python code for math, data analysis, and logic verification."

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    async def run(self, input_text: str) -> ToolResult:
        code = input_text.strip()
        if code.startswith("```"):
            code = re.sub(r"^```(?:python)?\s*", "", code)
            code = re.sub(r"\s*```$", "", code)

        # This code is UNTRUSTED and the in-process screen in metis.tools.sandbox is NOT a
        # boundary (three escapes past it were demonstrated in the 2026-09 re-audit). The
        # containment is here: a scrubbed environment so an escape finds no credentials, an
        # isolated working directory, POSIX resource limits, and a hard kill on timeout.
        from metis.security.child_env import scrub_child_env

        child_env = scrub_child_env(os.environ)
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        # cwd is an empty temp dir (FS hygiene: a relative path in a payload lands nowhere
        # useful), so the child must not depend on the parent's cwd to import `metis`. Pin the
        # parent's resolved import path explicitly — this works whether METIS is an installed
        # wheel or a source checkout on PYTHONPATH, and it is not sensitive so the scrub keeps
        # it. (`-I`/`-E` were tried and rejected: they drop exactly this path and broke the
        # source-run deployment.)
        # An empty sys.path entry MEANS "the current directory". Dropping it loses exactly
        # the entry a source checkout is found through, so resolve it instead of filtering it.
        child_env["PYTHONPATH"] = os.pathsep.join(
            dict.fromkeys(part or os.getcwd() for part in sys.path)
        )
        proc = None
        try:
            with tempfile.TemporaryDirectory(prefix="metis-sandbox-") as workdir:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "metis.tools.sandbox",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=child_env,
                    cwd=workdir,
                    preexec_fn=_child_rlimits if os.name == "posix" else None,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=code.encode("utf-8")),
                    timeout=self.timeout,
                )
            ok = proc.returncode == 0
            return ToolResult(
                name=self.name,
                success=ok,
                output=stdout.decode()[:8000],
                error=stderr.decode()[:2000],
            )
        except asyncio.TimeoutError:
            # communicate() timing out leaves the child ALIVE; without this a payload that
            # spins or blocks would leak a process on every call. Kill it, then reap it.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            return ToolResult(self.name, False, "", f"Timeout after {self.timeout}s")
        except Exception as e:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            return ToolResult(self.name, False, "", str(e))


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for current facts and information."

    def __init__(self, search_url: str = "https://html.duckduckgo.com/html/"):
        self.search_url = validate_url(search_url)

    async def run(self, input_text: str) -> ToolResult:
        query = input_text.strip()[:500]
        try:
            r = await safe_post(
                self.search_url,
                data={"q": query},
                headers={"User-Agent": "metis/0.1"},
            )
            r.raise_for_status()
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</',
                r.text,
                re.DOTALL,
            )[:5]
            clean = [re.sub(r"<[^>]+>", "", s).strip() for s in snippets]
            output = "\n".join(f"- {s}" for s in clean if s) or "No results found."
            wrapped = sanitize_tool_output(output)
            return ToolResult(self.name, True, wrapped)
        except Exception as e:
            return ToolResult(self.name, False, "", str(e))


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def descriptions(self) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in self._tools.values())

    async def execute(self, name: str, input_text: str) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(name, False, "", f"Unknown tool: {name}")
        start = time.perf_counter()
        result = await tool.run(input_text)
        latency_ms = (time.perf_counter() - start) * 1000
        emit_pipeline_event(
            PipelineEventKind.SEARCH_CALL if name == "web_search" else PipelineEventKind.TOOL_CALL,
            {"tool": name, "success": result.success, "latency_ms": round(latency_ms, 2)},
        )
        meter = get_current_meter()
        if meter:
            meter.record_mcp_tool(name, (time.perf_counter() - start) * 1000)
        if result.success and result.output:
            result.output = sanitize_tool_output(result.output)
        return result

    def names(self) -> list[str]:
        return list(self._tools.keys())


TOOL_USE_SYSTEM = """You decide whether to use a tool or answer directly.

Available tools:
{tools}

Respond with JSON only:
{{"action": "tool", "tool": "<name>", "input": "<query or code>"}}
or
{{"action": "answer", "content": "<your answer>"}}"""


async def agentic_tool_step(
    provider: LLMProvider,
    query: str,
    registry: ToolRegistry,
    *,
    context: str = "",
    observations: list[str] | None = None,
) -> tuple[str | None, ToolResult | None]:
    """One tool-use decision step. Returns (final_answer, tool_result)."""
    obs = "\n".join(observations or [])
    user = f"Task: {query}\n"
    if context:
        user += f"Context:\n{context}\n"
    if obs:
        user += f"Previous observations:\n{obs}\n"
    user += "What is your next action?"

    raw = await provider.complete_text(
        TOOL_USE_SYSTEM.format(tools=registry.descriptions()),
        user,
        temperature=0.2,
    )
    try:
        data = extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        return raw, None

    if data.get("action") == "answer":
        return data.get("content", raw), None

    if data.get("action") == "tool":
        result = await registry.execute(data.get("tool", ""), data.get("input", ""))
        return None, result

    return raw, None
