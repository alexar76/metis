"""Adversarial / edge-case regression tests for confidence gate.

Documents known limitation: high council-assigned confidence can PROCEED even when
interpretation is subtly wrong, if ambiguities do not set needs_user_input=True.

See metis/docs/en/MATURITY.md and docs/known-issues.md KI-8.
"""

import pytest

from metis.gates import GateAction, evaluate_confidence_gate
from metis.schemas.task_spec import Ambiguity, TaskSpec


def test_high_confidence_hidden_ambiguity_proceeds_known_gap():
    """Council marks 0.92 confidence but leaves ambiguity without needs_user_input — gate proceeds."""
    spec = TaskSpec(
        goal="Deploy to production",
        confidence=0.92,
        ambiguities=[Ambiguity(issue="Which region?", resolution="", needs_user_input=False)],
        success_criteria=["deployed"],
    )
    gate = evaluate_confidence_gate(spec, threshold=0.7)
    assert gate.action == GateAction.PROCEED
    # Documented gap: gate does not infer ambiguity severity without needs_user_input flag.


def test_low_base_confidence_clarifies_despite_bonuses():
    """Bonuses lift composite but needs_clarification still fires on raw confidence < threshold."""
    spec = TaskSpec(
        goal="x",
        confidence=0.36,
        constraints=["c1"],
        success_criteria=["s1"],
    )
    gate = evaluate_confidence_gate(spec, threshold=0.7, hard_floor=0.35)
    assert gate.action == GateAction.CLARIFY
    assert gate.composite_score == pytest.approx(0.44, abs=0.01)


def test_unresolved_user_ambiguity_always_clarifies():
    spec = TaskSpec(
        goal="build api",
        confidence=0.95,
        ambiguities=[Ambiguity(issue="Which API version?", needs_user_input=True)],
    )
    gate = evaluate_confidence_gate(spec, threshold=0.7)
    assert gate.action == GateAction.CLARIFY
