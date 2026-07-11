"""Verifier / critic — checks answer against TaskSpec."""

from __future__ import annotations

from dataclasses import dataclass

from metis.config import RuntimeConfig
from metis.models.provider import extract_json
from metis.modules.registry import ModuleRegistry
from metis.schemas.task_spec import TaskSpec

JUDGE_SYSTEM = """You are Judge. Verify the answer against the TaskSpec contract.

Check:
1. Does the answer achieve the GOAL?
2. Are CONSTRAINTS respected?
3. Are NON-GOALS avoided?
4. Are SUCCESS CRITERIA met?

Respond JSON:
{"pass": true/false, "score": 0.0-1.0, "feedback": "what to fix if fail", "checks": {"goal": true, "constraints": true, "non_goals": true, "criteria": true}}"""


@dataclass
class Verdict:
    passed: bool
    score: float
    feedback: str


async def verify_answer(
    config: RuntimeConfig,
    task_spec: TaskSpec,
    answer: str,
    user_query: str,
) -> Verdict:
    provider = ModuleRegistry(config).get_provider_for_role("judge")
    user = (
        f"TaskSpec:\n{task_spec.to_context()}\n\n"
        f"Original query:\n{user_query}\n\n"
        f"Answer to verify:\n{answer}"
    )
    raw = await provider.complete_text(JUDGE_SYSTEM, user, temperature=0.1)
    try:
        data = extract_json(raw)
        return Verdict(
            passed=bool(data.get("pass", False)),
            score=float(data.get("score", 0.0)),
            feedback=data.get("feedback", ""),
        )
    except ValueError:
        return Verdict(passed=False, score=0.0, feedback="Could not parse judge response")
