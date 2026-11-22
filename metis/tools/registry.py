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
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from metis.economy.meter import get_current_meter
from metis.models.provider import LLMProvider, extract_json
from metis.models.usage import MCPToolRef
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event
from metis.security import sanitize_tool_output
from metis.security.ssrf import safe_post, validate_url


@dataclass
class ToolResult:
    name: str
    success: bool
    output: str
    error: str = ""
    mcp_server: str | None = None


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
    mcp_server: str | None = None

    @abstractmethod
    async def run(self, input_text: str) -> ToolResult:
        ...


class CodeInterpreterTool(Tool):
    name = "code_interpreter"
    description = "Execute Python code for math, data analysis, and logic verification."

    def __init__(self, timeout: int = 10, *, production: bool = False):
        self.timeout = timeout
        self.production = production

    async def run(self, input_text: str) -> ToolResult:
        from metis.security.code_execution import host_execution_refusal

        refusal = host_execution_refusal(production=self.production)
        if refusal:
            return ToolResult(self.name, False, "", refusal)
        code = input_text.strip()
        if code.startswith("```"):
            code = re.sub(r"^```(?:python)?\s*", "", code)
            code = re.sub(r"\s*```$", "", code)

        # Reached only for trusted private development. These process hygiene
        # measures do not provide OS isolation from the host filesystem.
        from metis.security.child_env import scrub_child_env

        child_env = scrub_child_env(os.environ)
        child_env["METIS_UNSAFE_LOCAL_CODE"] = "1"  # only after the private-local policy passed
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


class TavilySearchTool(Tool):
    name = "web_search"
    description = "Search the web for current facts with source URLs and snippets."
    url = "https://api.tavily.com/search"

    def __init__(
        self, *, api_key: str | None = None, fallback_search_url: str | None = None,
        report_provider: Callable[[bool], None] | None = None,
    ):
        self._api_key = api_key
        self._fallback_search_url = fallback_search_url
        self._report_provider = report_provider

    async def _fallback(self, query: str, error: str) -> ToolResult:
        if self._api_key or not self._fallback_search_url:
            return ToolResult(self.name, False, "", error)
        try:
            result = await WebSearchTool(search_url=self._fallback_search_url).run(query)
        except ValueError:
            return ToolResult(self.name, False, "", error)
        if not result.success:
            return ToolResult(self.name, False, "", error)
        return ToolResult(self.name, True, "Search provider: DuckDuckGo (Tavily unavailable).\n" + result.output)

    async def run(self, input_text: str) -> ToolResult:
        query = input_text.strip()[:500]
        if not query:
            return ToolResult(self.name, False, "", "Search query is empty.")
        headers = (
            {"Authorization": f"Bearer {self._api_key}"}
            if self._api_key
            else {"X-Tavily-Access-Mode": "keyless"}
        )
        succeeded = False
        try:
            response = await safe_post(
                self.url, headers=headers, max_redirects=0,
                json_body={"query": query, "max_results": 5, "include_answer": False},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ValueError("Invalid Tavily response")
            sources = []
            for result in payload["results"][:5]:
                if not isinstance(result, dict):
                    continue
                url = result.get("url")
                if not isinstance(url, str) or len(url) > 2000 or any(c.isspace() for c in url):
                    continue
                try:
                    parsed = urlsplit(url)
                except ValueError:
                    continue
                if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                        or parsed.username is not None or parsed.password is not None):
                    continue
                title = result.get("title")
                content = result.get("content")
                title = " ".join(title[:240].split()) if isinstance(title, str) else ""
                content = " ".join(content[:640].split()) if isinstance(content, str) else ""
                sources.append(f"- {title or parsed.hostname}\n  {url}\n  {content}")
            output = "\n".join(sources) or "No results found."
            result = ToolResult(self.name, True, sanitize_tool_output(output))
            succeeded = True
            return result
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            advice = " Set METIS_TAVILY_API_KEY or retry later." if status == 429 and not self._api_key else ""
            error = f"Tavily search returned HTTP {status}.{advice}"
            if status == 429 or 500 <= status < 600:
                return await self._fallback(query, error)
            return ToolResult(self.name, False, "", error)
        except httpx.RequestError:
            return await self._fallback(query, "Tavily search did not return a usable response.")
        except ValueError:
            return ToolResult(self.name, False, "", "Tavily search did not return a usable response.")
        finally:
            if self._report_provider is not None:
                self._report_provider(succeeded)


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def descriptions(self) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in self._tools.values())

    def mcp_tool_refs(self) -> tuple[MCPToolRef, ...]:
        return tuple((tool.mcp_server, tool.name) for tool in self._tools.values() if tool.mcp_server)

    async def execute(self, name: str, input_text: str) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(name, False, "", f"Unknown tool: {name}")
        start = time.perf_counter()
        result = await tool.run(input_text)
        result.mcp_server = tool.mcp_server
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
    observation_sources: tuple[MCPToolRef, ...] = (),
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
        mcp_tools=registry.mcp_tool_refs(),
        mcp_results=observation_sources if obs else (),
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
