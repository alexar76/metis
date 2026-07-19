"""Additional tests for core module coverage."""

import pytest

from metis.config import ProviderKind, RuntimeConfig, RouteMode
from metis.router.classifier import _heuristic_route, route_query
from metis.thinking.extended import extended_thinking, self_consistency
from metis.validation import validate_task_spec_fields
from metis.models.provider import create_provider
from tests.support.mock_provider import MockProvider


@pytest.fixture
def mock_config(tmp_path):
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=2,
    )


@pytest.mark.asyncio
async def test_router_llm_classification(mock_config):
    route = await route_query(mock_config, "Build a complex distributed system")
    assert route in (RouteMode.COUNCIL, RouteMode.AGENT, RouteMode.THINKING, RouteMode.FAST)


def test_heuristic_oracle_route():
    route = _heuristic_route("use oracle vrf for randomness and reputation scoring")
    assert route in (RouteMode.AGENT, RouteMode.COUNCIL, RouteMode.FAST)


@pytest.mark.asyncio
async def test_extended_thinking(mock_config):
    provider = create_provider(mock_config.base_slot(), mock_config)
    reasoning, answer = await extended_thinking(provider, "What is 2+2?")
    assert answer


@pytest.mark.asyncio
async def test_self_consistency(mock_config):
    provider = create_provider(mock_config.base_slot(), mock_config)
    answer, samples = await self_consistency(provider, "test", n_samples=2, temperature=0.5)
    assert len(samples) == 2


def test_validate_task_spec_fields():
    data = {
        "goal": "test goal",
        "constraints": ["be accurate"],
        "confidence": 0.8,
    }
    result = validate_task_spec_fields(data)
    assert result.valid
    assert result.parsed is not None
    assert result.parsed["goal"] == "test goal"


def test_validate_json_output():
    from metis.validation import validate_json_output

    result = validate_json_output('{"goal": "x", "confidence": 0.9}', required_keys=["goal"])
    assert result.valid
