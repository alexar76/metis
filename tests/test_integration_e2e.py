"""End-to-end integration tests with mock provider only."""

import pytest

from metis.config import ProviderKind, RouteMode, RuntimeConfig
from metis.exoskeleton import Metis, RunStatus
from metis.pipeline.depth import DepthLevel


@pytest.fixture
def brain(tmp_path):
    return Metis(RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
        max_verify_retries=2,
        enable_long_term_memory=True,
        dgpd={"enabled": True, "agreement_threshold": 0.85},
    ))


@pytest.mark.asyncio
async def test_e2e_fast_l0(brain):
    result = await brain.run("Hello", route=RouteMode.FAST)
    assert result.status == RunStatus.SUCCESS
    assert result.depth == DepthLevel.L0_FAST
    assert result.answer


@pytest.mark.asyncio
async def test_e2e_thinking_l1(brain):
    result = await brain.run("Explain recursion", route=RouteMode.THINKING)
    assert result.status == RunStatus.SUCCESS
    assert result.metadata.get("phase") == "extended_thinking"


@pytest.mark.asyncio
async def test_e2e_council_l2_l3(brain):
    result = await brain.run(
        "Compare microservices vs monolith for a fintech startup",
        route=RouteMode.COUNCIL,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.task_spec is not None
    assert result.verify_score > 0
    assert result.metadata.get("depth") in ("L2", "L3")


@pytest.mark.asyncio
async def test_e2e_agent_l3(brain):
    result = await brain.run("Calculate factorial of 5 with code", route=RouteMode.AGENT)
    assert result.status == RunStatus.SUCCESS
    assert result.metadata.get("phase") == "agent_loop"


@pytest.mark.asyncio
async def test_e2e_memory_persistence(brain):
    await brain.run("Python is great", route=RouteMode.FAST)
    result = await brain.run("What did I say about Python?", route=RouteMode.FAST)
    assert result.status == RunStatus.SUCCESS


@pytest.mark.asyncio
async def test_e2e_openai_bridge(tmp_path):
    from metis.api.bridge import OpenAIMetisBridge

    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )
    bridge = OpenAIMetisBridge(Metis(cfg))
    out = await bridge.process(
        [{"role": "user", "content": "Summarize metis"}],
        model="metis-council",
    )
    assert out.content
    assert out.metadata["route"] == "council"


@pytest.mark.asyncio
async def test_agent_verify_failure_maps_to_error(brain, monkeypatch):
    """C1 regression: a failed verdict on the agent route must yield ERROR, not SUCCESS."""
    from metis.verify.critic import Verdict

    async def always_fail(*a, **k):
        return Verdict(passed=False, score=0.1, feedback="nope")

    monkeypatch.setattr("metis.exoskeleton.verify_answer", always_fail)
    result = await brain.run("Calculate factorial of 5 with code", route=RouteMode.AGENT)
    assert result.status == RunStatus.ERROR


@pytest.mark.asyncio
async def test_council_exhausted_retries_maps_to_error(brain, monkeypatch):
    """C2 regression: exhausting verify retries without a pass must yield ERROR."""
    from metis.verify.critic import Verdict

    async def always_fail(*a, **k):
        return Verdict(passed=False, score=0.1, feedback="nope")

    monkeypatch.setattr(brain, "_verify", always_fail)  # council goes through self._verify
    result = await brain.run("Compare microservices vs monolith", route=RouteMode.COUNCIL)
    assert result.status == RunStatus.ERROR


@pytest.mark.asyncio
async def test_episodic_memory_cleared_between_runs(brain):
    """H10 regression: episodic memory must not bleed across requests on a shared brain."""
    brain.episodic.record("tool:web_search", "SECRET caller-A observation", True)
    assert brain.episodic.episodes
    await brain.run("an unrelated question", route=RouteMode.FAST)
    assert brain.episodic.episodes == []
