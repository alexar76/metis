"""Router — dispatch by task complexity."""

from __future__ import annotations

import re

from metis.config import RouteMode, RuntimeConfig
from metis.models.provider import extract_json
from metis.modules.registry import ModuleRegistry

ROUTER_SYSTEM = """Classify the query. Respond JSON only:
{"mode": "fast"|"thinking"|"agent"|"council", "task_type": "factual"|"reasoning"|"coding"|"research"|"planning", "reason": "...", "scores": {"simplicity": 0-10, "ambiguity": 0-10, "tools_needed": 0-10}}

Routing rules:
- factual + low ambiguity → fast
- reasoning/explanation without tools → thinking
- coding/search/api/file → agent
- planning + high ambiguity or multi-step → council"""

ORACLE_MARKERS = re.compile(
    r"\b(random|oracle|reputation|vdf|lottery|verif(y|iable)|trust score)\b",
    re.I,
)

# Heuristic fallback when LLM unavailable
AMBIGUITY_MARKERS = re.compile(
    r"\b(or|either|maybe|perhaps|not sure|could you|what if|ambiguous|unclear)\b",
    re.I,
)
TOOL_MARKERS = re.compile(
    r"\b(code|run|execute|search|find|calculate|build|implement|debug|file|api)\b",
    re.I,
)


CODE_MARKERS = re.compile(
    r"\b(code|python|javascript|typescript|rust|golang|java|sql|regex|function|class|"
    r"implement|debug|compile|stack ?trace|exception|bug)\b",
    re.I,
)
FACT_MARKERS = re.compile(r"^\s*(what|who|when|where|which|how many|how much)\b", re.I)


def task_kind_of(query: str) -> str:
    """Keyword guess at the task kind (capability calibration's names), for when the LLM
    router did not classify the query."""
    if CODE_MARKERS.search(query):
        return "coding"
    if FACT_MARKERS.search(query) and len(query.split()) < 20:
        return "factual"
    return "reasoning"


async def route_query(config: RuntimeConfig, query: str) -> RouteMode:
    """Decide execution mode: fast / thinking / agent / council."""
    return (await classify_query(config, query))[0]


async def classify_query(config: RuntimeConfig, query: str) -> tuple[RouteMode, str | None]:
    """Execution mode plus the task kind the capability gate ranks models by.

    The kind is the LLM router's task_type when it gave one the calibration measures
    (reasoning, coding, factual); research and planning rank by the overall score (None).
    Without an LLM classification it is the keyword guess of `task_kind_of`.
    """
    if config.default_route != RouteMode.COUNCIL:
        return config.default_route, task_kind_of(query)

    # Oracle/ecosystem tool queries → agent (MCP tools available)
    if config.enable_mcp_tools and ORACLE_MARKERS.search(query):
        return RouteMode.AGENT, task_kind_of(query)

    try:
        provider = ModuleRegistry(config).get_provider_for_role("router")
        raw = await provider.complete_text(ROUTER_SYSTEM, query, temperature=0.1)
        data = extract_json(raw)
        mode = data.get("mode", "council")
        task_type = data.get("task_type", "")
        scores = data.get("scores", {})
        kind = task_type if task_type in ("reasoning", "coding", "factual") else None

        # Score-based overrides (deterministic layer on top of LLM router)
        if scores.get("tools_needed", 0) >= 7:
            return RouteMode.AGENT, kind
        if task_type in ("coding", "research"):
            return RouteMode.AGENT, kind
        if scores.get("ambiguity", 0) >= 7:
            return RouteMode.COUNCIL, kind
        if task_type == "factual" and scores.get("simplicity", 0) >= 7:
            return RouteMode.FAST, kind

        return RouteMode(mode), kind
    except Exception:
        return _heuristic_route(query), task_kind_of(query)


def _heuristic_route(query: str) -> RouteMode:
    words = len(query.split())
    if words < 15 and not AMBIGUITY_MARKERS.search(query) and not TOOL_MARKERS.search(query):
        return RouteMode.FAST
    if TOOL_MARKERS.search(query):
        return RouteMode.AGENT
    if AMBIGUITY_MARKERS.search(query) or words > 80:
        return RouteMode.COUNCIL
    return RouteMode.THINKING
