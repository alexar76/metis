"""Tool layer: code interpreter, web search, registry."""

from __future__ import annotations

import asyncio
import json
import re
import sys
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

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "metis.tools.sandbox",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            return ToolResult(self.name, False, "", f"Timeout after {self.timeout}s")
        except Exception as e:
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
