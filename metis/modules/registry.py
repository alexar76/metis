"""Module registry — role name → provider config with base-model fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from metis.config import ModelSlot, ModuleSlotConfig, ProviderKind, RuntimeConfig
from metis.distributed.security import resolve_api_key
from metis.models.provider import LLMProvider, create_provider

logger = logging.getLogger(__name__)

COUNCIL_ROLES: Tuple[str, ...] = (
    "intent_parser_a",
    "intent_parser_b",
    "intent_parser_c",
    "constraint_extractor",
    "ambiguity_hunter",
    "red_team",
    "synthesizer",
)

MOA_ROLES: Tuple[str, ...] = (
    "moa_proposer_logician",
    "moa_proposer_pragmatist",
    "moa_proposer_skeptic",
    "moa_refiner",
    "moa_aggregator",
)

OTHER_ROLES: Tuple[str, ...] = ("judge", "router")

ALL_MODULE_ROLES: Tuple[str, ...] = COUNCIL_ROLES + MOA_ROLES + OTHER_ROLES

PARSER_ROLES: Tuple[str, ...] = (
    "intent_parser_a",
    "intent_parser_b",
    "intent_parser_c",
)

# Legacy council_models name → module role
_LEGACY_NAME_MAP: Dict[str, str] = {
    "parser_a": "intent_parser_a",
    "parser_b": "intent_parser_b",
    "parser_c": "intent_parser_c",
    "constraint": "constraint_extractor",
    "ambiguity": "ambiguity_hunter",
    "red_team": "red_team",
    "synthesizer": "synthesizer",
}

_DEFAULT_TEMPERATURES: Dict[str, float] = {
    "intent_parser_a": 0.5,
    "intent_parser_b": 0.7,
    "intent_parser_c": 0.9,
    "constraint_extractor": 0.3,
    "ambiguity_hunter": 0.5,
    "red_team": 0.6,
    "synthesizer": 0.3,
    "moa_proposer_logician": 0.7,
    "moa_proposer_pragmatist": 0.7,
    "moa_proposer_skeptic": 0.7,
    "moa_refiner": 0.5,
    "moa_aggregator": 0.3,
    "judge": 0.1,
    "router": 0.1,
}


@dataclass
class ModuleValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    resolved: Dict[str, ModelSlot] = field(default_factory=dict)


class ModuleRegistry:
    """Resolve brain-module roles to ModelSlot / LLMProvider instances."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._providers: Dict[str, LLMProvider] = {}
        self._legacy_by_role = self._build_legacy_map()
        self._pool_cache: Optional[List[ModelSlot]] = None

    def _build_legacy_map(self) -> Dict[str, ModelSlot]:
        mapping: Dict[str, ModelSlot] = {}
        for slot in self.config.council_models:
            role = _LEGACY_NAME_MAP.get(slot.name, slot.name)
            copy = slot.model_copy()
            copy.name = role
            mapping[role] = copy
        return mapping

    def resolve_slot(self, role: str) -> ModelSlot:
        """Resolve ModelSlot for a brain role; falls back to base_model.

        When the capability gate is on, the resolution is then adjusted so a weak model
        can't sit in a high-leverage seat (aggregator/verifier/synthesizer → strongest) or
        vote as a below-floor proposer (swapped for the best floor-passing model).
        """
        mod = self.config.modules.get(role)
        if mod is not None:
            slot = self._slot_from_module(role, mod)
        elif role in self._legacy_by_role:
            slot = self._legacy_by_role[role]
        else:
            slot = self._fallback_slot(role)
        if getattr(self.config, "enforce_capability_gate", False):
            from metis.agents.capability import gate_role
            slot = gate_role(
                role, slot, self._reasoning_pool(),
                self.config.council_capability_floor,
                self.config.min_aggregator_capability,
            )
        return slot

    def _reasoning_pool(self) -> List[ModelSlot]:
        """Distinct models available for REASONING roles (base + council_models + non-vision
        module slots), deduped by model name. Used to rank models for capability gating."""
        if self._pool_cache is not None:
            return self._pool_cache
        candidates = [self.config.base_slot()]
        for r, mod in self.config.modules.items():
            if r == "vision" or not getattr(mod, "model", None):
                continue
            candidates.append(self._slot_from_module(r, mod))
        candidates.extend(self.config.council_models)
        seen: set = set()
        pool: List[ModelSlot] = []
        for s in candidates:
            if s.model not in seen:
                seen.add(s.model)
                pool.append(s)
        self._pool_cache = pool
        return pool

    def get_provider_for_role(self, role: str) -> LLMProvider:
        if role not in self._providers:
            self._providers[role] = create_provider(self.resolve_slot(role), self.config)
        return self._providers[role]

    async def aclose(self) -> None:
        """Close all cached provider HTTP clients."""
        for prov in self._providers.values():
            if hasattr(prov, "aclose"):
                await prov.aclose()
        self._providers.clear()

    def _slot_from_module(self, role: str, mod: ModuleSlotConfig) -> ModelSlot:
        base = self.config.base_slot()
        provider = mod.provider or base.provider
        api_key = resolve_api_key(
            mod.api_key_env,
            fallback=mod.api_key or base.api_key,
        )
        return ModelSlot(
            name=role,
            provider=provider,
            model=mod.model or base.model,
            base_url=(mod.base_url or base.base_url).rstrip("/"),
            api_key=api_key,
            temperature=(
                mod.temperature
                if mod.temperature is not None
                else _DEFAULT_TEMPERATURES.get(role, base.temperature)
            ),
            max_tokens=mod.max_tokens or base.max_tokens,
            node_id=mod.node_id,
            supports_vision=mod.supports_vision,
            extra_headers=mod.extra_headers or {},
        )

    def _fallback_slot(self, role: str) -> ModelSlot:
        base = self.config.base_slot()
        return ModelSlot(
            name=role,
            provider=base.provider,
            model=base.model,
            base_url=base.base_url,
            api_key=base.api_key,
            temperature=_DEFAULT_TEMPERATURES.get(role, base.temperature),
            max_tokens=base.max_tokens,
            node_id=None,
        )

    def resolved_council_slots(self) -> List[ModelSlot]:
        """Council slots in pipeline order."""
        return [self.resolve_slot(role) for role in COUNCIL_ROLES]

    def validate(self) -> ModuleValidationResult:
        errors: List[str] = []
        warnings: List[str] = []
        resolved: Dict[str, ModelSlot] = {}

        for role in ALL_MODULE_ROLES:
            slot = self.resolve_slot(role)
            resolved[role] = slot
            mod = self.config.modules.get(role)
            if mod and mod.api_key_env:
                if not os.environ.get(mod.api_key_env):
                    msg = f"{role}: env var {mod.api_key_env} is not set"
                    if self.config.production:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

        warnings.extend(check_parser_diversity_warning(self))

        return ModuleValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            resolved=resolved,
        )

    def show_modules(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for role in ALL_MODULE_ROLES:
            slot = self.resolve_slot(role)
            source = "modules" if role in self.config.modules else (
                "council_models" if role in self._legacy_by_role else "base_model"
            )
            rows.append({
                "role": role,
                "model": slot.model,
                "provider": slot.provider.value,
                "endpoint": slot.base_url,
                "node_id": slot.node_id or "",
                "temperature": str(slot.temperature),
                "source": source,
            })
        return rows


def check_parser_diversity_warning(registry: ModuleRegistry) -> List[str]:
    """Warn when intent parsers share model+endpoint (weak ensemble diversity)."""
    warnings: List[str] = []
    signatures: Dict[Tuple[str, str], List[str]] = {}
    for role in PARSER_ROLES:
        slot = registry.resolve_slot(role)
        key = (slot.model, slot.base_url)
        signatures.setdefault(key, []).append(role)

    for (model, endpoint), roles in signatures.items():
        if len(roles) >= 2:
            warnings.append(
                f"Intent parsers {', '.join(roles)} share model={model!r} "
                f"and endpoint={endpoint!r}; use different models or endpoints "
                "for reliable council diversity."
            )
    return warnings


def resolve_vision_slot(config: RuntimeConfig) -> Optional[ModelSlot]:
    """Pick the slot that should handle image input, deterministically.

    Priority: an explicit ``modules.vision`` entry → any vision-capable council/
    module slot → the base model if it can see → ``None`` (no vision anywhere).
    """
    from metis.models.provider import model_supports_vision

    reg = ModuleRegistry(config)
    if "vision" in config.modules:
        return reg.resolve_slot("vision")
    # Prefer an explicitly vision-capable configured slot.
    for role in COUNCIL_ROLES + MOA_ROLES:
        slot = reg.resolve_slot(role)
        if model_supports_vision(slot):
            return slot
    base = config.base_slot()
    if model_supports_vision(base):
        return base
    return None


def get_provider_for_role(config: RuntimeConfig, role: str) -> LLMProvider:
    return ModuleRegistry(config).get_provider_for_role(role)


def resolve_slot_for_role(config: RuntimeConfig, role: str) -> ModelSlot:
    return ModuleRegistry(config).resolve_slot(role)
