"""Tests for metis."""

import pytest

from metis.config import ProviderKind, RuntimeConfig, RouteMode
from metis.exoskeleton import Metis, RunStatus
from metis.memory.store import VectorMemory
from metis.router.classifier import _heuristic_route
from metis.schemas.task_spec import Ambiguity, TaskSpec
from metis.tools.registry import CodeInterpreterTool, ToolRegistry


@pytest.fixture
def mock_config(tmp_path):
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
        max_verify_retries=1,
    )


@pytest.mark.asyncio
async def test_fast_route(mock_config):
    exo = Metis(mock_config)
    result = await exo.run("Hello", route=RouteMode.FAST)
    assert result.status == RunStatus.SUCCESS
    assert result.answer


@pytest.mark.asyncio
async def test_council_route(mock_config):
    exo = Metis(mock_config)
    result = await exo.run(
        "Build a distributed system for task understanding",
        route=RouteMode.COUNCIL,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.task_spec is not None
    assert result.task_spec.confidence > 0


@pytest.mark.asyncio
async def test_thinking_route(mock_config):
    exo = Metis(mock_config)
    result = await exo.run("Explain recursion", route=RouteMode.THINKING)
    assert result.status == RunStatus.SUCCESS


@pytest.mark.asyncio
async def test_agent_route(mock_config):
    exo = Metis(mock_config)
    result = await exo.run("Calculate 2+2 with code", route=RouteMode.AGENT)
    assert result.status == RunStatus.SUCCESS


def test_task_spec_clarification():
    spec = TaskSpec(
        goal="test",
        confidence=0.5,
        ambiguities=[Ambiguity(issue="What format?", needs_user_input=True)],
    )
    assert spec.needs_clarification()
    assert len(spec.clarification_questions()) >= 1


def test_heuristic_router():
    assert _heuristic_route("Hi") == RouteMode.FAST
    assert _heuristic_route("Write code to parse JSON files") == RouteMode.AGENT
    assert _heuristic_route("Maybe we should either do A or B, not sure") == RouteMode.COUNCIL


@pytest.mark.asyncio
async def test_code_interpreter():
    tool = CodeInterpreterTool(timeout=5)
    result = await tool.run("print(2 + 2)")
    assert result.success
    assert "4" in result.output


def test_vector_memory(tmp_path):
    mem = VectorMemory(tmp_path / "vec.json")
    mem.add("Python is a programming language")
    mem.add("Cats are animals")
    hits = mem.search("programming language python")
    assert len(hits) >= 1
    assert "Python" in hits[0].content


@pytest.mark.asyncio
async def test_tool_registry():
    reg = ToolRegistry([CodeInterpreterTool()])
    result = await reg.execute("code_interpreter", "print('ok')")
    assert result.success
    assert "ok" in result.output
