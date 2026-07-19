"""Search, env compat, and economy bridge tests."""

import os

import pytest

from metis.config import ProviderKind, RuntimeConfig
from metis.economy.bridge import BudgetExceededError, EcosystemBridge
from metis.economy.config import EconomyConfig
from metis.economy.cost import CostCalculator
from metis.economy.meter import UsageMeter
from metis.env_compat import migrate_legacy_env
from metis.tools.registry import WebSearchTool


def test_env_compat_migration(monkeypatch):
    monkeypatch.delenv("METIS_API_KEY", raising=False)
    monkeypatch.setenv("SUPERBRAIN_API_KEY", "migrated")
    migrate_legacy_env()
    assert os.environ.get("METIS_API_KEY") == "migrated"


def test_env_compat_does_not_override(monkeypatch):
    monkeypatch.setenv("METIS_API_KEY", "primary")
    monkeypatch.setenv("COGNITIVE_API_KEY", "secondary")
    migrate_legacy_env()
    assert os.environ["METIS_API_KEY"] == "primary"


def test_cost_calculator():
    cfg = EconomyConfig(enabled=True)
    calc = CostCalculator(cfg)
    est = calc.estimate_route_cost("council", "gpt-4", 1000)
    assert est.estimated_usd >= 0


def test_ecosystem_bridge_budget_exceeded():
    cfg = EconomyConfig(
        enabled=True,
        session_budget_usd=0.0,
        require_budget_for_routes=["council"],
        models={"gpt-4": {"input_per_1m": 5.0, "output_per_1m": 15.0}},
    )
    bridge = EcosystemBridge(cfg)
    with pytest.raises(BudgetExceededError):
        bridge.check_budget_before_route("council", "gpt-4", 5000)


def test_ecosystem_bridge_finalize():
    cfg = EconomyConfig(enabled=True)
    bridge = EcosystemBridge(cfg)
    meter = UsageMeter(route="fast")
    meter.record_llm(
        model="gpt-4",
        provider="mock",
        role="base",
        tokens_in=100,
        tokens_out=50,
        latency_ms=10.0,
    )
    report = bridge.finalize(meter)
    assert report.route == "fast"
    assert report.total_tokens_in == 100


@pytest.mark.asyncio
async def test_web_search_tool_runs():
    tool = WebSearchTool()
    result = await tool.run("metis multi-agent orchestrator")
    assert result.name == "web_search"
