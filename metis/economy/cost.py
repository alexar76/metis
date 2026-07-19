"""Cost calculation."""

from __future__ import annotations

from dataclasses import dataclass

from metis.economy.config import EconomyConfig
from metis.economy.meter import UsageMeter

ROUTE_CALL_ESTIMATES = {
    "fast": 1,
    "thinking": 2,
    "agent": 6,
    "council": 12,
}


@dataclass
class CostEstimate:
    route: str
    estimated_usd: float
    currency: str
    basis: str


class CostCalculator:
    def __init__(self, config: EconomyConfig):
        self.config = config

    def estimate_route_cost(self, route: str, model: str, avg_tokens: int = 2000) -> CostEstimate:
        pricing = self.config.pricing_for(model)
        calls = ROUTE_CALL_ESTIMATES.get(route, 5)
        tokens_in = avg_tokens * calls
        tokens_out = avg_tokens * calls // 2
        cost = (tokens_in / 1_000_000) * pricing.input_per_1m + (tokens_out / 1_000_000) * pricing.output_per_1m
        return CostEstimate(route=route, estimated_usd=cost, currency=self.config.currency, basis=f"{calls} calls")

    def compute_report_cost(self, meter: UsageMeter) -> float:
        total = 0.0
        for event in meter.events:
            if event.mcp_tool:
                continue
            p = self.config.pricing_for(event.model)
            total += (event.tokens_in / 1_000_000) * p.input_per_1m
            total += (event.tokens_out / 1_000_000) * p.output_per_1m
        return total
