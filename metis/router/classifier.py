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


async def route_query(config: RuntimeConfig, query: str) -> RouteMode:
    """Decide execution mode: fast / thinking / agent / council."""
    if config.default_route != RouteMode.COUNCIL:
        return config.default_route

    # Oracle/ecosystem tool queries → agent (MCP tools available)
    if config.enable_mcp_tools and ORACLE_MARKERS.search(query):
        return RouteMode.AGENT

    try:
        provider = ModuleRegistry(config).get_provider_for_role("router")
        raw = await provider.complete_text(ROUTER_SYSTEM, query, temperature=0.1)
        data = extract_json(raw)
        mode = data.get("mode", "council")
        task_type = data.get("task_type", "")
        scores = data.get("scores", {})

        # Score-based overrides (deterministic layer on top of LLM router)
        if scores.get("tools_needed", 0) >= 7:
            return RouteMode.AGENT
        if task_type in ("coding", "research"):
            return RouteMode.AGENT
        if scores.get("ambiguity", 0) >= 7:
            return RouteMode.COUNCIL
        if task_type == "factual" and scores.get("simplicity", 0) >= 7:
            return RouteMode.FAST

        return RouteMode(mode)
    except Exception:
        return _heuristic_route(query)


def _heuristic_route(query: str) -> RouteMode:
    words = len(query.split())
    if words < 15 and not AMBIGUITY_MARKERS.search(query) and not TOOL_MARKERS.search(query):
        return RouteMode.FAST
    if TOOL_MARKERS.search(query):
        return RouteMode.AGENT
    if AMBIGUITY_MARKERS.search(query) or words > 80:
        return RouteMode.COUNCIL
    return RouteMode.THINKING
