"""Confidence gate — fail-closed routing before expensive solve paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from metis.schemas.task_spec import TaskSpec


class GateAction(str, Enum):
    PROCEED = "proceed"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


@dataclass
class ConfidenceGateResult:
    action: GateAction
    composite_score: float
    reason: str


def evaluate_confidence_gate(
    task_spec: TaskSpec,
    *,
    threshold: float = 0.7,
    hard_floor: float = 0.35,
) -> ConfidenceGateResult:
    """
    Mandatory gate before council/agent solve paths.

    Uses TaskSpec confidence plus structural signals (not model self-report alone).
    - composite < hard_floor → clarify (fail-closed)
    - composite < threshold → clarify
    - unresolved ambiguities → clarify
    """
    ambiguity_penalty = sum(
        0.1 for a in task_spec.ambiguities if a.needs_user_input and not a.resolution
    )
    criteria_bonus = 0.05 if task_spec.success_criteria else 0.0
    constraint_bonus = 0.03 if task_spec.constraints else 0.0

    composite = max(0.0, min(1.0, task_spec.confidence - ambiguity_penalty + criteria_bonus + constraint_bonus))

    if task_spec.needs_clarification(threshold):
        return ConfidenceGateResult(
            action=GateAction.CLARIFY,
            composite_score=composite,
            reason="Unresolved ambiguities or confidence below threshold",
        )

    if composite < hard_floor:
        return ConfidenceGateResult(
            action=GateAction.CLARIFY,
            composite_score=composite,
            reason=f"Composite confidence {composite:.2f} below hard floor {hard_floor}",
        )

    if composite < threshold:
        return ConfidenceGateResult(
            action=GateAction.CLARIFY,
            composite_score=composite,
            reason=f"Composite confidence {composite:.2f} below threshold {threshold}",
        )

    return ConfidenceGateResult(
        action=GateAction.PROCEED,
        composite_score=composite,
        reason="Confidence gate passed",
    )
