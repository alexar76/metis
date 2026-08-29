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


def _brain(tmp_path, budget, retries=3):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        council_budget_seconds=budget,
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
