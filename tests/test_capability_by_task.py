"""Per-task capability: a model strong at arithmetic is not assumed strong at code.

An outside review (2026-10-23) noted that one number per model hides this. `metis calibrate`
now measures reasoning, coding and factual sets separately and the gate ranks by the kind of
the query being answered, when this deployment measured it.
"""
from __future__ import annotations

import io
import contextlib

import pytest

from metis.agents import capability as cap
from metis.config import ModelSlot, ProviderKind
from metis.router.classifier import task_kind_of


def _slot(model, name="x"):
    return ModelSlot(name=name, provider=ProviderKind.OPENAI_COMPAT, model=model,
                     base_url="https://x/v1", api_key="k")


@pytest.fixture(autouse=True)
def _clean_calibration():
    before = dict(cap._CALIBRATED), {k: dict(v) for k, v in cap._CALIBRATED_BY_TASK.items()}
    cap._CALIBRATED.clear()
    cap._CALIBRATED_BY_TASK.clear()
    yield
    cap._CALIBRATED.clear()
    cap._CALIBRATED.update(before[0])
    cap._CALIBRATED_BY_TASK.clear()
    cap._CALIBRATED_BY_TASK.update(before[1])


def test_old_flat_calibration_files_still_load():
    cap.load_calibration({"vendor/model-a": 81.0})
    assert cap.capability_of("model-a") == 81.0
    assert cap.capability_of("model-a", "coding") == 81.0   # no task score: overall


def test_per_task_scores_rank_by_the_task_and_fall_back_to_overall():
    cap.load_calibration({
        "model-a": {"overall": 80.0, "reasoning": 100.0, "coding": 50.0, "factual": 90.0},
        "model-b": {"overall": 78.0, "reasoning": 62.5, "coding": 100.0, "factual": 75.0},
    })
    assert cap.capability_of("model-a") == 80.0
    assert cap.capability_of("model-a", "coding") == 50.0
    assert cap.capability_of("model-b", "coding") == 100.0
    assert cap.capability_of("model-b", "planning") == 78.0
    pool = [_slot("model-a"), _slot("model-b")]
    assert cap.strongest(pool).model == "model-a"
    assert cap.strongest(pool, "coding").model == "model-b"


def test_overall_defaults_to_the_mean_of_the_tasks_and_junk_is_ignored():
    cap.load_calibration({"model-c": {"reasoning": 90.0, "coding": 60.0, "factual": True}})
    assert cap.capability_of("model-c") == 75.0
    assert cap.capability_of("model-c", "factual") == 75.0   # a bool is not a score


def test_gate_seats_the_aggregator_by_the_current_task_kind():
    cap.load_calibration({
        "model-a": {"overall": 90.0, "reasoning": 100.0, "coding": 50.0},
        "model-b": {"overall": 85.0, "reasoning": 70.0, "coding": 100.0},
    })
    pool = [_slot("model-a"), _slot("model-b")]
    resolved = _slot("model-a", "moa_aggregator")
    assert cap.gate_role("moa_aggregator", resolved, pool, 60, 75).model == "model-a"
    token = cap.set_task_kind("coding")
    try:
        assert cap.current_task_kind() == "coding"
        assert cap.gate_role("moa_aggregator", resolved, pool, 60, 75).model == "model-b"
    finally:
        cap.reset_task_kind(token)
    assert cap.current_task_kind() is None
    assert cap.set_task_kind("research").var.get() is None   # not a measured kind


def test_a_proposer_below_the_floor_for_this_task_loses_its_vote():
    cap.load_calibration({
        "model-a": {"overall": 80.0, "coding": 40.0},
        "model-b": {"overall": 70.0, "coding": 90.0},
    })
    pool = [_slot("model-a"), _slot("model-b")]
    proposer = _slot("model-a", "moa_proposer_logician")
    assert cap.gate_role("moa_proposer_logician", proposer, pool, 60, 75).model == "model-a"
    assert cap.gate_role("moa_proposer_logician", proposer, pool, 60, 75, task="coding").model == "model-b"


def test_every_coding_answer_is_what_the_program_prints():
    for code, want in cap.CODING_SET:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(code, {})
        assert int(out.getvalue().strip()) == want, code


def test_each_task_kind_has_a_set_of_the_same_size():
    assert set(cap.CALIBRATION_SETS) == set(cap.TASK_KINDS)
    assert {len(v) for v in cap.CALIBRATION_SETS.values()} == {8}


class _Provider:
    """Answers reasoning and factual questions right and code questions wrong."""

    def __init__(self):
        self.closed = False

    async def complete_text(self, system, prompt, temperature=0.0):
        for q, n in cap.CALIBRATION_SET + cap.FACTUAL_SET:
            if prompt.startswith(q):
                return f"Answer: {n}"
        return "Answer: 0"

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_calibrate_by_task_scores_each_set(monkeypatch):
    prov = _Provider()
    monkeypatch.setattr("metis.models.provider.create_provider", lambda slot, config: prov)
    scores = await cap.calibrate_model_by_task(_slot("model-a"), config=None)
    assert scores == {"reasoning": 100.0, "coding": 0.0, "factual": 100.0, "overall": 66.7}
    assert prov.closed
    assert await cap.calibrate_model(_slot("model-a"), config=None) == 100.0
    pool = await cap.calibrate_pool([_slot("model-a"), _slot("model-a")], None, ("coding",))
    assert pool == {"model-a": {"coding": 0.0, "overall": 0.0}}


@pytest.mark.parametrize("query, kind", [
    ("Why does this Python function raise KeyError?", "coding"),
    ("Debug my SQL query", "coding"),
    ("What is the capital of Australia?", "factual"),
    ("How many moons does Mars have?", "factual"),
    ("Plan a three-step migration and explain the trade-offs between the options", "reasoning"),
])
def test_task_kind_keyword_guess(query, kind):
    assert task_kind_of(query) == kind
