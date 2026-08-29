"""Layered Mixture-of-Agents for solution synthesis."""

from __future__ import annotations

import asyncio
import logging

from metis.config import RuntimeConfig
from metis.modules.registry import ModuleRegistry
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event
from metis.pipeline.agreement import compute_proposer_agreement
from metis.pipeline.depth import requires_full_depth
from metis.schemas.task_spec import TaskSpec
from metis.agents.diversity import check_council_diversity

logger = logging.getLogger(__name__)

PROPOSER_ROLES = [
    ("moa_proposer_logician", "logician", "You reason formally. Find logical structure and edge cases."),
    ("moa_proposer_pragmatist", "pragmatist", "You find the simplest effective solution. Minimize scope."),
    ("moa_proposer_skeptic", "skeptic", "You challenge assumptions. Find holes and risks."),
]

REFINER_SYSTEM = """You are a refiner in a Mixture-of-Agents layer.
You see proposals from other agents. Improve and synthesize the best ideas.
Do NOT simply copy one proposal — merge strengths and fix weaknesses."""

AGGREGATOR_SYSTEM = """You are the final aggregator. Produce the best unified answer.
Be direct, complete, and aligned with the TaskSpec.
Write the answer in natural, conversational prose for the end user — never as JSON, a
key/value object, a "constraints"/"goal" structure, or code — unless the user explicitly
asked for that format. Do not restate the task specification; just answer."""


def _should_skip_refiner(query: str, config: RuntimeConfig, agreement: float) -> bool:
    if not config.dgpd.enabled:
        return False
    if requires_full_depth(query, config):
        return False
    return agreement >= config.dgpd.agreement_threshold


async def _layer_within_budget(
    coros: list,
    role_names: list[str],
    timeout: float | None,
) -> tuple[list[int], list[str], list[str]]:
    """Run proposers concurrently and refuse to let one slow generation hold the layer.

    ``gather`` waits for the slowest member. In production one skeptic ran 400s while its
    two peers finished in 33s, so a layer worth 33s of wall clock cost 400s — a third of
    the caller's whole budget for a single proposal that was not better than the others.

    We keep whoever answered inside ``timeout`` and drop the stragglers. If nobody made
    the budget we wait for the first one however long it takes, because a layer with no
    proposals has nothing to refine.

    Returns (kept indices, kept outputs, dropped role names).
    """
    tasks = [asyncio.ensure_future(c) for c in coros]
    if timeout and timeout > 0:
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        if not done and pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
    else:
        done, pending = await asyncio.wait(tasks), set()

    kept_idx: list[int] = []
    kept_out: list[str] = []
    dropped: list[str] = []
    stragglers = []
    for i, task in enumerate(tasks):
        if task.done() and not task.cancelled() and task.exception() is None:
            kept_idx.append(i)
            kept_out.append(task.result())
            continue
        if not task.done():
            task.cancel()
            stragglers.append(task)
        dropped.append(role_names[i])
    if stragglers:
        # Await the cancellations so the loop does not log "task was destroyed but is pending".
        await asyncio.gather(*stragglers, return_exceptions=True)
    if dropped:
        logger.info("MoA layer 1 dropped %s after %ss", ", ".join(dropped), timeout)
    return kept_idx, kept_out, dropped


async def run_layered_moa(
    config: RuntimeConfig,
    task_spec: TaskSpec,
    user_query: str,
    *,
    feedback: str = "",
    skip_refiner: bool = False,
) -> tuple[str, dict]:
    """Layer 1: diverse proposers. Layer 2: refiners. Layer 3: aggregator.

    Architecture follows Wang et al. (ICLR 2025) arXiv:2406.04692; heterogeneity
    checked via check_council_diversity (Yang et al. 2026; contrast Li et al. 2025 Self-MoA).
    """
    registry = ModuleRegistry(config)
    slots = registry.resolved_council_slots()
    diversity = check_council_diversity(
        slots,
        enforce=config.enforce_heterogeneous_agents,
        min_unique_models=config.min_unique_council_models,
    )
    _ = diversity  # warnings logged when enforce=False

    # Layer 1 — parallel proposers with different roles
    layer1_tasks = []
    for role_key, role_name, role_desc in PROPOSER_ROLES:
        prov = registry.get_provider_for_role(role_key)
        system = f"You are the {role_name} proposer. {role_desc}"
        user = _build_moa_prompt(task_spec, user_query, feedback)
        layer1_tasks.append(prov.complete_text(system, user, temperature=0.7))

    kept_idx, layer1_outputs, dropped = await _layer_within_budget(
        layer1_tasks,
        [name for _key, name, _desc in PROPOSER_ROLES],
        config.role_timeout_seconds,
    )
    agreement = compute_proposer_agreement(list(layer1_outputs))
    meta = {"agreement": agreement, "skip_refiner": False}
    if dropped:
        meta["dropped_proposers"] = dropped

    # Label each proposal with the role that actually wrote it: a dropped straggler shifts
    # every later index, so enumerate() over the survivors would misattribute the rest.
    layer1_block = "\n\n".join(
        f"--- Proposal {n+1} ({PROPOSER_ROLES[idx][1]}) ---\n{out}"
        for n, (idx, out) in enumerate(zip(kept_idx, layer1_outputs))
    )

    if skip_refiner or _should_skip_refiner(user_query, config, agreement):
        meta["skip_refiner"] = True
        emit_pipeline_event(PipelineEventKind.MOA_LAYER2, {"skip_refiner": True, "agreement": agreement})
        layer2_output = layer1_block
    else:
        emit_pipeline_event(PipelineEventKind.MOA_LAYER2, {"skip_refiner": False, "agreement": agreement})
        refiner = registry.get_provider_for_role("moa_refiner")
        layer2_input = f"TaskSpec:\n{task_spec.to_context()}\n\nProposals:\n{layer1_block}"
        layer2_output = await refiner.complete_text(REFINER_SYSTEM, layer2_input, temperature=0.5)

    emit_pipeline_event(PipelineEventKind.MOA_LAYER3, {})
    aggregator = registry.get_provider_for_role("moa_aggregator")
    layer3_input = (
        f"TaskSpec:\n{task_spec.to_context()}\n\n"
        f"Original query: {user_query}\n\n"
        f"Refined synthesis:\n{layer2_output}"
    )
    if feedback:
        layer3_input += f"\n\nJudge feedback (fix these issues):\n{feedback}"

    answer = await aggregator.complete_text(AGGREGATOR_SYSTEM, layer3_input, temperature=0.3)
    return answer, meta


def _build_moa_prompt(task_spec: TaskSpec, user_query: str, feedback: str) -> str:
    parts = [task_spec.to_context(), f"\nUser query:\n{user_query}"]
    if feedback:
        parts.append(f"\nPrevious attempt failed verification:\n{feedback}")
    return "\n".join(parts)
