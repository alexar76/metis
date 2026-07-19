"""Plan → Act → Observe → Reflect agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from metis.config import RuntimeConfig
from metis.memory.store import EpisodicMemory, WorkingMemory
from metis.models.provider import create_provider, extract_json
from metis.schemas.task_spec import TaskSpec
from metis.tools.registry import ToolRegistry, agentic_tool_step

PLAN_SYSTEM = """You are a planner. Decompose the task into concrete steps.
Respond JSON: {"plan": ["step 1", "step 2", ...], "current_step": 0}"""

REFLECT_SYSTEM = """You reflect on the last action. What worked? What failed? What next?
Respond JSON: {"assessment": "...", "success": true/false, "next_action": "continue|retry|finish", "notes": "..."}"""


@dataclass
class AgentState:
    plan: list[str] = field(default_factory=list)
    step_index: int = 0
    observations: list[str] = field(default_factory=list)
    answer: str = ""
    done: bool = False


async def run_agent_loop(
    config: RuntimeConfig,
    task_spec: TaskSpec,
    user_query: str,
    tools: ToolRegistry,
    *,
    working: WorkingMemory | None = None,
    episodic: EpisodicMemory | None = None,
) -> AgentState:
    """Full Plan-Act-Observe-Reflect cycle with tool use."""
    provider = create_provider(config.base_slot(), config)
    working = working or WorkingMemory()
    episodic = episodic or EpisodicMemory()
    state = AgentState()

    context = task_spec.to_context()
    if episodic.summary():
        context += "\n" + episodic.summary()

    # Plan
    plan_raw = await provider.complete_text(
        PLAN_SYSTEM,
        f"{context}\n\nTask: {user_query}",
        temperature=0.3,
    )
    try:
        plan_data = extract_json(plan_raw)
        state.plan = plan_data.get("plan", ["Analyze and solve the task"])
    except ValueError:
        state.plan = ["Analyze and solve the task"]

    for iteration in range(config.max_agent_iterations):
        if state.done:
            break

        current = state.plan[state.step_index] if state.step_index < len(state.plan) else "Finalize answer"
        working.set_scratchpad(f"Step {state.step_index + 1}: {current}")

        # Act — tool use or direct answer
        answer, tool_result = await agentic_tool_step(
            provider,
            f"{user_query}\n\nCurrent step: {current}",
            tools,
            context=context,
            observations=state.observations,
        )

        # Observe
        if tool_result:
            obs = f"Tool {tool_result.name}: success={tool_result.success}\n{tool_result.output or tool_result.error}"
            state.observations.append(obs)
            episodic.record(f"tool:{tool_result.name}", obs[:300], tool_result.success)
        elif answer:
            state.observations.append(f"Draft answer: {answer[:500]}")
            state.answer = answer

        # Reflect
        reflect_raw = await provider.complete_text(
            REFLECT_SYSTEM,
            f"Plan: {state.plan}\nStep: {current}\nObservations:\n" + "\n".join(state.observations[-3:]),
            temperature=0.2,
        )
        try:
            reflection = extract_json(reflect_raw)
            next_action = reflection.get("next_action", "continue")
            episodic.record(current, reflection.get("assessment", ""), reflection.get("success", False))

            if next_action == "finish" and state.answer:
                state.done = True
                break
            if next_action == "continue":
                state.step_index = min(state.step_index + 1, len(state.plan) - 1)
        except ValueError:
            if answer:
                state.done = True
                state.answer = answer
                break

    if not state.answer and state.observations:
        state.answer = state.observations[-1]

    return state
