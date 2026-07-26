"""Verifier / critic — checks answer against TaskSpec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


# Float-repr slack. A judge (or an upstream blend) landing on 1.0000000002 is stating
# 1.0; anything further out is not a number on this scale at all.
_SCORE_EPSILON = 1e-9


def clamp_score(raw: Any) -> float:
    """Coerce whatever the judge put in `score` into a usable [0, 1] confidence.

    The judge is an LLM answering in free-form JSON, but this number leaves Metis in
    the /v1/verify envelope and is compared against a money-movement bar by the hub's
    Pay-on-Verified escrow. Four shapes have to be neutralised here rather than
    downstream, because downstream only sees a float:

      * a non-numeric score (`null`, "high") — ``float()`` raises TypeError, which the
        old ``except ValueError`` did not catch, so it escaped as a 500 on the council
        path instead of a failed verdict;
      * NaN — silently false against every comparison;
      * a NEGATIVE score — folded up to 0.0, the bottom of the scale, which is the
        direction that refuses;
      * a score ABOVE the scale (a judge answering ``95`` for "95%") — 0.0, the same
        as an unreadable one. Folding it DOWN to 1.0 would be the tempting move and it
        is the wrong one: it hands the maximum possible confidence to a judge that
        just demonstrated it is not answering on the demanded scale, and every ``>=
        threshold`` comparison downstream — including the hub's capture decision —
        then passes trivially. A gate that cannot read the number must refuse, not
        round it towards paying.
    """
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if val != val:  # NaN: every comparison against it is False, including its own
        return 0.0
    if val > 1.0 + _SCORE_EPSILON:
        return 0.0
    return min(1.0, max(0.0, val))


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
            score=clamp_score(data.get("score", 0.0)),
            feedback=str(data.get("feedback", "") or ""),
        )
    except ValueError:
        return Verdict(passed=False, score=0.0, feedback="Could not parse judge response")
