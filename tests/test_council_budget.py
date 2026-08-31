"""The council must answer within the caller's patience, or hand back what it has.

Two production failures motivate this file:

* One proposer generated for 400 seconds while its two peers finished in 33. Layer 1 runs
  concurrently, so the layer cost what its slowest member cost — a third of the caller's
  whole budget spent on one proposal that was not better for the wait.
* The council retries until it is satisfied. With no notion of a deadline it started a
  round it could not finish; the caller's timeout killed it mid-round, and a run that had
  an aggregated answer at minute 14 handed back nothing at minute 20.
"""

from __future__ import annotations

import asyncio

import pytest

from metis.agents.moa import _layer_within_budget


async def _slow(value: str, seconds: float) -> str:
    await asyncio.sleep(seconds)
    return value


@pytest.mark.asyncio
async def test_a_straggler_does_not_hold_the_layer():
    kept_idx, kept_out, dropped = await _layer_within_budget(
        [_slow("logician", 0.01), _slow("pragmatist", 0.01), _slow("skeptic", 5.0)],
        ["logician", "pragmatist", "skeptic"],
        timeout=0.2,
    )
    assert kept_out == ["logician", "pragmatist"]
    assert kept_idx == [0, 1]
    assert dropped == ["skeptic"]


@pytest.mark.asyncio
async def test_the_layer_returns_before_the_straggler_would_have():
    started = asyncio.get_running_loop().time()
    await _layer_within_budget(
        [_slow("fast", 0.01), _slow("slow", 5.0)], ["fast", "slow"], timeout=0.2
    )
    assert asyncio.get_running_loop().time() - started < 1.0


@pytest.mark.asyncio
async def test_surviving_proposals_keep_their_own_role_label():
    # Dropping the FIRST proposer shifts every later position. Labelling survivors by
    # enumeration would credit the pragmatist's proposal to the logician.
    kept_idx, kept_out, dropped = await _layer_within_budget(
        [_slow("logician", 5.0), _slow("pragmatist", 0.01), _slow("skeptic", 0.01)],
        ["logician", "pragmatist", "skeptic"],
        timeout=0.2,
    )
    assert kept_idx == [1, 2]
    assert kept_out == ["pragmatist", "skeptic"]
    assert dropped == ["logician"]


@pytest.mark.asyncio
async def test_when_nobody_makes_the_budget_we_still_get_one_proposal():
    # A layer with no proposals has nothing to refine, so the budget yields to necessity.
    kept_idx, kept_out, dropped = await _layer_within_budget(
        [_slow("a", 0.6), _slow("b", 5.0)], ["a", "b"], timeout=0.05
    )
    assert kept_out == ["a"]
    assert dropped == ["b"]


@pytest.mark.asyncio
async def test_a_failing_proposer_is_dropped_not_raised():
    async def boom() -> str:
        raise RuntimeError("provider refused")

    kept_idx, kept_out, dropped = await _layer_within_budget(
        [boom(), _slow("ok", 0.01)], ["logician", "pragmatist"], timeout=0.5
    )
    assert kept_out == ["ok"]
    assert dropped == ["logician"]


@pytest.mark.asyncio
async def test_no_timeout_means_wait_for_everyone():
    kept_idx, kept_out, dropped = await _layer_within_budget(
        [_slow("a", 0.01), _slow("b", 0.05)], ["a", "b"], timeout=None
    )
    assert kept_out == ["a", "b"]
    assert dropped == []


# --- the wall-clock budget -------------------------------------------------------------

import metis.exoskeleton as exo
from metis.config import ProviderKind, RuntimeConfig
from metis.schemas.task_spec import TaskSpec
from metis.verify.critic import Verdict


def _brain(tmp_path, budget, retries=3, role_cap=0.1):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        council_budget_seconds=budget,
        role_timeout_seconds=role_cap,
        max_verify_retries=retries,
        thinking_samples=1,          # keep self-consistency out of this test
        enable_long_term_memory=False,
        enable_grounded_verify=False,
        memory_dir=tmp_path,
    )
    return exo.Metis(cfg)


def _always_fails_verify(round_seconds):
    """A council whose rounds cost `round_seconds` and never satisfy the judge."""

    async def fake_moa(config, task_spec, query, *, feedback="", skip_refiner=False):
        await asyncio.sleep(round_seconds)
        return f"draft after {round_seconds}s", {"agreement": 0.5}

    async def fake_verify(self, task_spec, answer, query):
        return Verdict(False, 0.4, "not good enough")

    return fake_moa, fake_verify


@pytest.mark.asyncio
async def test_the_council_stops_starting_rounds_it_cannot_finish(tmp_path, monkeypatch):
    fake_moa, fake_verify = _always_fails_verify(round_seconds=0.3)
    monkeypatch.setattr(exo, "run_layered_moa", fake_moa)
    monkeypatch.setattr(exo.Metis, "_verify", fake_verify)

    brain = _brain(tmp_path, budget=0.45, retries=5)
    spec = TaskSpec(goal="prove it")
    result = await brain._run_council(spec, "prove it", "", exo.RouteMode.COUNCIL)

    # One round fits in 0.45s; a second (another 0.3s) does not start.
    assert result.metadata["rounds_completed"] == 1
    assert result.metadata["verify_warning"] == "wall-clock budget exhausted"
    assert result.metadata["best_effort"] is True


@pytest.mark.asyncio
async def test_it_hands_back_the_answer_it_has_rather_than_nothing(tmp_path, monkeypatch):
    fake_moa, fake_verify = _always_fails_verify(round_seconds=0.3)
    monkeypatch.setattr(exo, "run_layered_moa", fake_moa)
    monkeypatch.setattr(exo.Metis, "_verify", fake_verify)

    brain = _brain(tmp_path, budget=0.45, retries=5)
    result = await brain._run_council(TaskSpec(goal="g"), "g", "", exo.RouteMode.COUNCIL)

    # The API returns any non-empty content; an empty answer is what the caller used to get.
    assert result.answer == "draft after 0.3s"


@pytest.mark.asyncio
async def test_without_a_budget_it_spends_every_retry(tmp_path, monkeypatch):
    fake_moa, fake_verify = _always_fails_verify(round_seconds=0.01)
    monkeypatch.setattr(exo, "run_layered_moa", fake_moa)
    monkeypatch.setattr(exo.Metis, "_verify", fake_verify)

    brain = _brain(tmp_path, budget=None, retries=3)
    result = await brain._run_council(TaskSpec(goal="g"), "g", "", exo.RouteMode.COUNCIL)

    assert result.metadata["rounds_completed"] == 3
    assert result.metadata["verify_warning"] == "max retries reached"


@pytest.mark.asyncio
async def test_a_budget_never_blocks_a_council_that_passes(tmp_path, monkeypatch):
    async def fake_moa(config, task_spec, query, *, feedback="", skip_refiner=False):
        return "good answer", {"agreement": 0.9}

    async def passing_verify(self, task_spec, answer, query):
        return Verdict(True, 0.95, "")

    monkeypatch.setattr(exo, "run_layered_moa", fake_moa)
    monkeypatch.setattr(exo.Metis, "_verify", passing_verify)

    brain = _brain(tmp_path, budget=0.001, retries=3)
    result = await brain._run_council(TaskSpec(goal="g"), "g", "", exo.RouteMode.COUNCIL)

    assert result.status == exo.RunStatus.SUCCESS
    assert result.answer == "good answer"
    assert "best_effort" not in result.metadata


def test_the_ceiling_is_arithmetic_not_history(tmp_path):
    """A round's worst case comes from the role cap, not from what past rounds cost."""
    brain = _brain(tmp_path, budget=10.0, role_cap=1.5)
    # four capped hops: proposer layer, refiner, aggregator, verifier
    assert brain._round_ceiling() == 6.0
    uncapped = _brain(tmp_path, budget=10.0, role_cap=0)
    assert uncapped._round_ceiling() == 0.0


@pytest.mark.asyncio
async def test_a_fast_history_does_not_license_a_slow_round(tmp_path, monkeypatch):
    """The failure this replaces: two 250s rounds taught it to expect 250s, the third took 660s.

    With a ceiling of role_cap x 4, cheap early rounds can no longer talk the council into
    starting a round that could overrun the caller.
    """
    fake_moa, fake_verify = _always_fails_verify(round_seconds=0.02)
    monkeypatch.setattr(exo, "run_layered_moa", fake_moa)
    monkeypatch.setattr(exo.Metis, "_verify", fake_verify)

    # Rounds cost 0.02s, so a history-based estimate would happily start many more.
    # The ceiling (0.5 x 4 = 2.0s) exceeds the 1.0s budget, so exactly one round runs.
    brain = _brain(tmp_path, budget=1.0, retries=9, role_cap=0.5)
    result = await brain._run_council(TaskSpec(goal="g"), "g", "", exo.RouteMode.COUNCIL)

    assert result.metadata["rounds_completed"] == 1
    assert result.metadata["verify_warning"] == "wall-clock budget exhausted"


@pytest.mark.asyncio
async def test_a_slow_refiner_falls_back_to_the_proposals(monkeypatch):
    """A capped serial role yields its input rather than the caller's whole budget."""
    from metis.agents.moa import _role_within_budget

    async def slow():
        await asyncio.sleep(5.0)
        return "refined"

    started = asyncio.get_running_loop().time()
    out = await _role_within_budget(slow(), 0.15, fallback="raw proposals", role="moa_refiner")
    assert out == "raw proposals"
    assert asyncio.get_running_loop().time() - started < 1.0


@pytest.mark.asyncio
async def test_a_role_inside_its_budget_is_not_disturbed(monkeypatch):
    from metis.agents.moa import _role_within_budget

    async def quick():
        return "refined"

    assert await _role_within_budget(quick(), 5.0, fallback="raw", role="moa_refiner") == "refined"


# ── a clarification needs somebody to answer it ───────────────────────────────────
#
# Measured on the live loop: a remediation run spent six understanding-council roles and
# 37k tokens building a TaskSpec, the confidence gate scored it under threshold, and the whole
# run was discarded. The caller received "no content" and escalated to the human it was there
# to spare. The gate is code; the "you are answering an autonomous caller" note in the prompt
# is prose, and a gate does not read prose.

from metis.api.bridge import AUTONOMOUS_MODELS, caller_is_autonomous, model_to_route  # noqa: E402


def test_an_autonomous_model_id_is_recognised():
    assert caller_is_autonomous("metis-council-autonomous")
    assert caller_is_autonomous("METIS-COUNCIL-AUTONOMOUS")
    assert not caller_is_autonomous("metis-council")
    assert not caller_is_autonomous("metis")


def test_an_autonomous_id_routes_to_the_same_place_as_its_ordinary_twin():
    # It changes who may be asked a question, not which stack runs.
    assert model_to_route("metis-council-autonomous") == model_to_route("metis-council")
    assert model_to_route("metis-thinking-autonomous") == model_to_route("metis-thinking")


def test_every_autonomous_id_has_a_route():
    for name in AUTONOMOUS_MODELS:
        assert model_to_route(name) is not None, f"{name} maps to no route"


def _gate_says_clarify(monkeypatch):
    from metis.gates import GateAction

    class _Gate:
        action = GateAction.CLARIFY
        composite_score = 0.31
        reason = "the request is terse and technical"

    monkeypatch.setattr(exo, "evaluate_confidence_gate", lambda *a, **k: _Gate())


def _council_that_answers(monkeypatch):
    async def fake_understanding(*a, **k):
        return TaskSpec(goal="fix the manifest signature", confidence=0.31)

    async def fake_moa(config, task_spec, query, *, feedback="", skip_refiner=False):
        return "a best-effort answer", {"agreement": 0.5}

    async def passing_verify(self, task_spec, answer, query):
        return Verdict(True, 0.8, "")

    monkeypatch.setattr(exo, "run_understanding_council", fake_understanding)
    monkeypatch.setattr(exo, "run_layered_moa", fake_moa)
    monkeypatch.setattr(exo.Metis, "_verify", passing_verify)


@pytest.mark.asyncio
async def test_a_caller_with_a_human_still_gets_the_question(tmp_path, monkeypatch):
    brain = _brain(tmp_path, budget=None, retries=1)
    brain.config.enforce_confidence_gate = True
    _gate_says_clarify(monkeypatch)
    _council_that_answers(monkeypatch)

    result = await brain.run("fix it", route=exo.RouteMode.COUNCIL)

    assert result.status == exo.RunStatus.NEEDS_CLARIFICATION
    assert result.answer == ""


@pytest.mark.asyncio
async def test_a_caller_with_nobody_to_ask_gets_an_answer_instead(tmp_path, monkeypatch):
    """The failure this replaces, measured on the live loop.

    Six understanding-council roles and 37k tokens went into a TaskSpec, the gate scored it
    under threshold, and the run was discarded. The caller received "no content" and escalated
    to the human it existed to spare. A clarification question needs somebody to answer it.
    """
    brain = _brain(tmp_path, budget=None, retries=1)
    brain.config.enforce_confidence_gate = True
    _gate_says_clarify(monkeypatch)
    _council_that_answers(monkeypatch)

    result = await brain.run("fix it", route=exo.RouteMode.COUNCIL, autonomous_caller=True)

    assert result.status != exo.RunStatus.NEEDS_CLARIFICATION
    assert result.answer == "a best-effort answer"


@pytest.mark.asyncio
async def test_the_gate_is_still_evaluated_for_an_autonomous_caller(tmp_path, monkeypatch):
    # Proceeding is not the same as not looking. The score must still be produced, so an
    # operator reading the trace can see the answer was weak.
    seen = {}

    from metis.gates import GateAction

    class _Gate:
        action = GateAction.CLARIFY
        composite_score = 0.31
        reason = "terse"

    def _spy(*a, **k):
        seen["evaluated"] = True
        return _Gate()

    brain = _brain(tmp_path, budget=None, retries=1)
    brain.config.enforce_confidence_gate = True
    monkeypatch.setattr(exo, "evaluate_confidence_gate", _spy)
    _council_that_answers(monkeypatch)

    await brain.run("fix it", route=exo.RouteMode.COUNCIL, autonomous_caller=True)
    assert seen.get("evaluated") is True


def test_the_autonomous_ids_are_advertised():
    from metis.api.bridge import AVAILABLE_MODELS

    # A caller cannot use a model id it cannot discover.
    assert "metis-council-autonomous" in AVAILABLE_MODELS
