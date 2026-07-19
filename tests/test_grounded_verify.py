"""Grounded verifier: verify_score grounded in real code execution, not opinion."""

from __future__ import annotations

import pytest

from metis.config import RuntimeConfig
from metis.schemas.task_spec import TaskSpec
from metis.tools.registry import CodeInterpreterTool, ToolRegistry
from metis.verify import grounded as gmod
from metis.verify.critic import Verdict


@pytest.fixture
def cfg():
    return RuntimeConfig(enable_grounded_verify=True, confidence_threshold=0.7)


@pytest.fixture
def spec():
    return TaskSpec(goal="compute a value", confidence=0.9)


@pytest.fixture
def tools():
    return ToolRegistry([CodeInterpreterTool(timeout=15)])


@pytest.fixture(autouse=True)
def _stub_judge(monkeypatch):
    """Pin the LLM judge so we test the *grounding* logic deterministically."""
    async def _judge(config, task_spec, answer, user_query):
        return Verdict(passed=True, score=0.8, feedback="looks fine")
    monkeypatch.setattr(gmod, "verify_answer", _judge)


def test_extract_code_blocks():
    md = "text\n```python\nprint(1)\n```\nmore\n```\nx=2\n```"
    blocks = gmod.extract_code_blocks(md)
    assert len(blocks) == 2
    assert "print(1)" in blocks[0]


async def test_clean_code_corroborates(cfg, spec, tools):
    answer = "Here is the check:\n```python\nassert 2 + 2 == 4\nprint('ok', 4)\n```"
    v = await gmod.grounded_verify(cfg, spec, answer, "add 2 and 2", tools)
    assert v.grounded is True
    assert v.passed is True
    assert v.score >= 0.8  # blended judge (0.8) + grounding boost
    assert any("✓" in e for e in v.evidence)


async def test_failing_code_forces_fail(cfg, spec, tools):
    # The judge said pass@0.8, but the code raises — grounding must override.
    answer = "Solution:\n```python\nraise ValueError('boom')\n```"
    v = await gmod.grounded_verify(cfg, spec, answer, "do it", tools)
    assert v.grounded is True
    assert v.passed is False
    assert v.score <= 0.35
    assert any("✗" in e for e in v.evidence)
    assert "code failed" in v.feedback


async def test_no_code_falls_back_to_judge(cfg, spec, tools):
    v = await gmod.grounded_verify(cfg, spec, "Just prose, no code.", "q", tools)
    assert v.grounded is False
    assert v.passed is True and v.score == 0.8


async def test_disabled_returns_plain_judge(spec, tools):
    cfg = RuntimeConfig(enable_grounded_verify=False)
    answer = "```python\nraise ValueError('x')\n```"
    v = await gmod.grounded_verify(cfg, spec, answer, "q", tools)
    assert v.grounded is False
    assert v.passed is True and v.score == 0.8  # code NOT executed


async def test_no_tools_is_safe(cfg, spec):
    v = await gmod.grounded_verify(cfg, spec, "```python\nprint(1)\n```", "q", tools=None)
    assert v.grounded is False
    assert v.passed is True
