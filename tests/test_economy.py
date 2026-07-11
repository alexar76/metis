"""Economy module tests."""

import pytest

from metis.economy.config import EconomyConfig, ModelPricing
from metis.economy.cost import CostCalculator
from metis.economy.meter import UsageMeter
from metis.economy.bridge import EcosystemBridge, BudgetExceededError


def test_cost_calculator():
    config = EconomyConfig(
        enabled=True,
        models={"gpt-4o": ModelPricing(input_per_1m=2.50, output_per_1m=10.00)},
    )
    calc = CostCalculator(config)
    est = calc.estimate_route_cost("council", "gpt-4o", avg_tokens=1000)
    assert est.estimated_usd > 0


def test_usage_meter():
    meter = UsageMeter(route="fast")
    meter.record_llm(model="qwen3:8b", provider="local", role="base", tokens_in=100, tokens_out=50, latency_ms=200)
    report = meter.build_report(estimated_cost_usd=0.0)
    assert report.total_tokens_in == 100
    assert report.total_tokens_out == 50


def test_budget_gate():
    bridge = EcosystemBridge(EconomyConfig(
        enabled=True,
        session_budget_usd=0.001,
        models={"gpt-4o": ModelPricing(input_per_1m=2.50, output_per_1m=10.00)},
    ))
    with pytest.raises(BudgetExceededError):
        bridge.check_budget_before_route("council", "gpt-4o", query_length=5000)
