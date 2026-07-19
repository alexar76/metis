"""Tests for confidence gate and diversity enforcement."""

import pytest

from metis.agents.diversity import check_council_diversity, diversify_temperatures
from metis.config import ModelSlot, ProviderKind
from metis.gates import GateAction, evaluate_confidence_gate
from metis.schemas.task_spec import Ambiguity, TaskSpec


def test_confidence_gate_proceed():
    spec = TaskSpec(goal="build api", confidence=0.85, success_criteria=["works"])
    gate = evaluate_confidence_gate(spec, threshold=0.7)
    assert gate.action == GateAction.PROCEED
    assert gate.composite_score >= 0.7


def test_confidence_gate_clarify_low_confidence():
    spec = TaskSpec(goal="unclear task", confidence=0.3)
    gate = evaluate_confidence_gate(spec, threshold=0.7, hard_floor=0.35)
    assert gate.action == GateAction.CLARIFY


def test_confidence_gate_clarify_ambiguity():
    spec = TaskSpec(
        goal="test",
        confidence=0.8,
        ambiguities=[Ambiguity(issue="Which format?", needs_user_input=True)],
    )
    gate = evaluate_confidence_gate(spec, threshold=0.7)
    assert gate.action == GateAction.CLARIFY


def test_diversity_warn_homogeneous():
    slots = [
        ModelSlot(name="a", model="qwen3:8b", base_url="http://localhost:11434/v1"),
        ModelSlot(name="b", model="qwen3:8b", base_url="http://localhost:11434/v1"),
    ]
    report = check_council_diversity(slots, enforce=False)
    assert not report.is_heterogeneous
    assert report.warnings


def test_diversity_enforce_raises():
    slots = [
        ModelSlot(name="a", model="qwen3:8b", base_url="http://localhost:11434/v1"),
        ModelSlot(name="b", model="qwen3:8b", base_url="http://localhost:11434/v1"),
    ]
    with pytest.raises(ValueError):
        check_council_diversity(slots, enforce=True)


def test_diversify_temperatures():
    slots = [ModelSlot(name="a", model="m", base_url="http://x", temperature=0.5)]
    spread = diversify_temperatures(slots * 3)
    temps = {s.temperature for s in spread}
    assert len(temps) >= 2
