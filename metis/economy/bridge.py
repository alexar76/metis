"""Ecosystem economy bridge."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

import httpx

from metis.economy.config import EconomyConfig
from metis.economy.cost import CostCalculator, CostEstimate
from metis.economy.meter import UsageMeter, UsageReport

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    def __init__(self, spent: float, budget: float, route: str):
        super().__init__(f"Budget exceeded: ${spent:.4f} > ${budget:.4f} (route={route})")
        self.spent = spent
        self.budget = budget
        self.route = route


class EcosystemBridge:
    def __init__(self, config: EconomyConfig):
        self.config = config
        self.calculator = CostCalculator(config)
        self._session_spent = 0.0

    def check_budget_before_route(self, route: str, model: str, query_length: int = 0) -> CostEstimate:
        if not self.config.enabled or self.config.session_budget_usd is None:
            return CostEstimate(route=route, estimated_usd=0.0, currency=self.config.currency, basis="disabled")
        if route not in self.config.require_budget_for_routes:
            return CostEstimate(route=route, estimated_usd=0.0, currency=self.config.currency, basis="exempt")
        avg = max(500, min(query_length * 4, 8000))
        est = self.calculator.estimate_route_cost(route, model, avg)
        if self._session_spent + est.estimated_usd > self.config.session_budget_usd:
            raise BudgetExceededError(self._session_spent + est.estimated_usd, self.config.session_budget_usd, route)
        return est

    def finalize(self, meter: UsageMeter) -> UsageReport:
        cost = self.calculator.compute_report_cost(meter)
        self._session_spent += cost
        report = meter.build_report(estimated_cost_usd=cost, currency=self.config.currency)
        if self.config.export_events:
            self._export(report.to_dict())
        return report

    def _export(self, payload: Dict[str, Any]) -> None:
        payload["source"] = "metis"
        logger.info("usage_report %s", json.dumps(payload, default=str))
        if self.config.webhook_url:
            try:
                with httpx.Client(timeout=10.0) as c:
                    c.post(self.config.webhook_url, json=payload)
            except Exception as e:
                logger.warning("webhook failed: %s", e)
