"""Per-module LLM configuration registry."""

from metis.modules.registry import (
    ALL_MODULE_ROLES,
    ModuleRegistry,
    ModuleValidationResult,
    get_provider_for_role,
    resolve_slot_for_role,
)

__all__ = [
    "ALL_MODULE_ROLES",
    "ModuleRegistry",
    "ModuleValidationResult",
    "get_provider_for_role",
    "resolve_slot_for_role",
]
