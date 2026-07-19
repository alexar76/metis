"""Economy module."""

from metis.economy.config import EconomyConfig, ModelPricing
from metis.economy.meter import UsageMeter, UsageReport, get_current_meter, set_current_meter
from metis.economy.bridge import EcosystemBridge, BudgetExceededError

__all__ = [
    "EconomyConfig",
    "ModelPricing",
    "UsageMeter",
    "UsageReport",
    "get_current_meter",
    "set_current_meter",
    "EcosystemBridge",
    "BudgetExceededError",
    "CostCalculator",
    "CostEstimate",
    "TrackedProvider",
]


def __getattr__(name: str):
    if name == "CostCalculator":
        from metis.economy.cost import CostCalculator
        return CostCalculator
    if name == "CostEstimate":
        from metis.economy.cost import CostEstimate
        return CostEstimate
    if name == "TrackedProvider":
        from metis.economy.tracked import TrackedProvider
        return TrackedProvider
    raise AttributeError(name)
