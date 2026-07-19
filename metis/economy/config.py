"""Economy configuration."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    input_per_1m: float = 0.0
    output_per_1m: float = 0.0
    provider_label: str = "local"


class EconomyConfig(BaseModel):
    enabled: bool = False
    currency: str = "USD"
    models: Dict[str, ModelPricing] = Field(default_factory=dict)
    session_budget_usd: Optional[float] = None
    require_budget_for_routes: List[str] = Field(default_factory=lambda: ["council", "agent"])
    webhook_url: Optional[str] = None
    aimarket_hub_url: Optional[str] = None
    export_events: bool = True

    def pricing_for(self, model: str) -> ModelPricing:
        if model in self.models:
            return self.models[model]
        for key, pricing in self.models.items():
            if model.startswith(key) or key.startswith(model.split(":")[0]):
                return pricing
        return ModelPricing(provider_label="unknown")
