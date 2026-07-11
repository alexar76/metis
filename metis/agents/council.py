"""Understanding Council — distributed task interpretation for breakthrough understanding."""

from __future__ import annotations

import asyncio
import json

from metis.config import RuntimeConfig
from metis.models.provider import LLMProvider, extract_json
from metis.modules.registry import ModuleRegistry
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event
from metis.schemas.task_spec import Ambiguity, TaskSpec
from metis.validation import validate_task_spec_fields

INTENT_SYSTEM = """You are IntentParser agent #{idx} ({name}).
Analyze the user request. What do they want as OUTPUT?
Respond JSON: {{"goal": "...", "assumptions": ["..."], "implicit_needs": ["..."]}}"""

CONSTRAINT_SYSTEM = """You are ConstraintExtractor.
Find explicit and implicit constraints, format requirements, forbidden actions.
Respond JSON: {{"constraints": ["..."], "non_goals": ["..."]}}"""

AMBIGUITY_SYSTEM = """You are AmbiguityHunter.
List ambiguities and alternative readings.
Respond JSON: {{"ambiguities": [{{"issue": "...", "options": ["..."], "needs_user_input": true/false}}]}}"""

REDTEAM_SYSTEM = """You are RedTeam. Attack the obvious interpretation.
How could this request be misunderstood? What traps exist?
Respond JSON: {{"wrong_readings": ["..."], "traps": ["..."], "alternative_goals": ["..."]}}"""

SYNTHESIZER_SYSTEM = """You are TaskSynthesizer. Merge all agent interpretations into one TaskSpec.
Resolve ambiguities where possible. Set confidence 0-1.
Respond JSON:
{{
  "goal": "...",
  "constraints": ["..."],
  "non_goals": ["..."],
  "ambiguities": [{{"issue": "...", "resolution": "...", "needs_user_input": false}}],
  "success_criteria": ["..."],
  "required_tools": ["code"|"search"|"none"],
  "confidence": 0.85
}}"""

PARSER_ROLES = ("intent_parser_a", "intent_parser_b", "intent_parser_c")


async def run_understanding_council(
    config: RuntimeConfig,
    user_query: str,
    *,
    memory_context: str = "",
    knowledge_context: str = "",
) -> TaskSpec:
    """Parallel heterogeneous agents interpret the task, then synthesize TaskSpec.

    Agents are isolated (no peer visibility) to reduce sycophantic drift seen in
    naive SLM debate (MMAD, OpenReview 0h3dbL6Iy3; CONSENSAGENT, ACL 2025).
    Diversity enforced via per-module config — Yang et al. 2026.
    """
    registry = ModuleRegistry(config)

    query_block = user_query
    if memory_context:
        query_block = f"{memory_context}\n\nUser request:\n{user_query}"
    if knowledge_context:
        query_block = f"{knowledge_context}\n\n{query_block}"

    intent_tasks = []
    for i, role in enumerate(PARSER_ROLES):
        prov = registry.get_provider_for_role(role)
        sys_prompt = INTENT_SYSTEM.format(idx=i + 1, name=role)
        intent_tasks.append(_safe_json_call(prov, sys_prompt, query_block))

    constraint_prov = registry.get_provider_for_role("constraint_extractor")
    ambiguity_prov = registry.get_provider_for_role("ambiguity_hunter")
    redteam_prov = registry.get_provider_for_role("red_team")
    synth_prov = registry.get_provider_for_role("synthesizer")

    # Light all six understanding-council agents as they fire (they run
    # concurrently, so this is emitted once with the full roster).
    emit_pipeline_event(PipelineEventKind.COUNCIL_STARTED, {
        "agents": list(PARSER_ROLES) + ["constraint_extractor", "ambiguity_hunter", "red_team"],
    })

    results = await asyncio.gather(
        *intent_tasks,
        _safe_json_call(constraint_prov, CONSTRAINT_SYSTEM, query_block),
        _safe_json_call(ambiguity_prov, AMBIGUITY_SYSTEM, query_block),
        _safe_json_call(redteam_prov, REDTEAM_SYSTEM, query_block),
        return_exceptions=True,
    )

    interpretations: dict[str, str] = {}
    labels = ["intent_a", "intent_b", "intent_c", "constraints", "ambiguity", "redteam"]
    for label, res in zip(labels, results):
        if isinstance(res, Exception):
            interpretations[label] = json.dumps({"error": str(res)})
        else:
            interpretations[label] = json.dumps(res, ensure_ascii=False)

    synth_input = "Agent interpretations:\n" + "\n\n".join(
        f"=== {k} ===\n{v}" for k, v in interpretations.items()
    ) + f"\n\nOriginal request:\n{user_query}"

    spec_data = await _safe_json_call(synth_prov, SYNTHESIZER_SYSTEM, synth_input)

    validation = validate_task_spec_fields(spec_data)
    if not validation.valid:
        spec_data.setdefault("confidence", 0.4)
        spec_data.setdefault("goal", user_query)

    ambiguities = [
        Ambiguity(
            issue=a.get("issue", ""),
            resolution=a.get("resolution", ""),
            needs_user_input=bool(a.get("needs_user_input", False)),
        )
        for a in spec_data.get("ambiguities", [])
    ]

    tools = spec_data.get("required_tools", [])
    if isinstance(tools, str):
        tools = [tools] if tools != "none" else []
    if not isinstance(tools, list):
        tools = []

    return TaskSpec(
        goal=spec_data.get("goal", user_query),
        constraints=spec_data.get("constraints", []),
        non_goals=spec_data.get("non_goals", []),
        ambiguities=ambiguities,
        success_criteria=spec_data.get("success_criteria", ["Address the user's request"]),
        required_tools=[t for t in tools if t and t != "none"],
        confidence=float(spec_data.get("confidence", 0.5)),
        raw_interpretations=interpretations,
    )


async def _safe_json_call(provider: LLMProvider, system: str, user: str) -> dict:
    raw = await provider.complete_text(system, user, temperature=0.3)
    try:
        return extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        return {"raw": raw}
