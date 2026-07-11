"""Tests for per-module configuration registry."""

from __future__ import annotations

import pytest

from metis.config import ModuleSlotConfig, ProviderKind, RuntimeConfig
from metis.modules.registry import ModuleRegistry, check_parser_diversity_warning


@pytest.fixture
def base_config() -> RuntimeConfig:
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        base_model="base-model",
        base_url="http://localhost:9999/v1",
        api_key="test",
        enforce_capability_gate=False,  # these tests exercise raw role→endpoint plumbing;
        #                                 the capability gate is a separate layer (test_capability.py)
    )


def test_module_registry_resolves_roles(base_config: RuntimeConfig) -> None:
    base_config.modules = {
        "intent_parser_a": ModuleSlotConfig(model="model-a"),
        "judge": ModuleSlotConfig(model="judge-model", provider=ProviderKind.MOCK),
    }
    registry = ModuleRegistry(base_config)

    slot_a = registry.resolve_slot("intent_parser_a")
    assert slot_a.model == "model-a"
    assert slot_a.name == "intent_parser_a"

    judge = registry.resolve_slot("judge")
    assert judge.model == "judge-model"

    provider = registry.get_provider_for_role("judge")
    assert provider is registry.get_provider_for_role("judge")


def test_fallback_to_base_model(base_config: RuntimeConfig) -> None:
    registry = ModuleRegistry(base_config)
    slot = registry.resolve_slot("moa_aggregator")

    assert slot.model == "base-model"
    assert slot.base_url == "http://localhost:9999/v1"
    assert slot.provider == ProviderKind.MOCK


def test_diversity_warning_same_model(base_config: RuntimeConfig) -> None:
    base_config.modules = {
        "intent_parser_a": ModuleSlotConfig(model="same-model", base_url="http://a/v1"),
        "intent_parser_b": ModuleSlotConfig(model="same-model", base_url="http://a/v1"),
    }
    registry = ModuleRegistry(base_config)
    warnings = check_parser_diversity_warning(registry)

    assert any("intent_parser_a" in w and "intent_parser_b" in w for w in warnings)


def test_per_module_different_endpoints(base_config: RuntimeConfig) -> None:
    base_config.modules = {
        "intent_parser_a": ModuleSlotConfig(
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
        ),
        "intent_parser_b": ModuleSlotConfig(
            model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
        ),
        "synthesizer": ModuleSlotConfig(
            provider=ProviderKind.ANTHROPIC,
            model="claude-sonnet-4-20250514",
        ),
    }
    registry = ModuleRegistry(base_config)

    a = registry.resolve_slot("intent_parser_a")
    b = registry.resolve_slot("intent_parser_b")
    synth = registry.resolve_slot("synthesizer")

    assert a.base_url == "https://api.deepseek.com/v1"
    assert b.base_url == "https://api.openai.com/v1"
    assert synth.provider == ProviderKind.ANTHROPIC

    rows = registry.show_modules()
    by_role = {r["role"]: r for r in rows}
    assert by_role["intent_parser_a"]["endpoint"] == "https://api.deepseek.com/v1"
    assert by_role["intent_parser_b"]["endpoint"] == "https://api.openai.com/v1"
    assert by_role["moa_aggregator"]["source"] == "base_model"


def test_validate_reports_missing_api_key_env(base_config: RuntimeConfig, monkeypatch) -> None:
    monkeypatch.delenv("MISSING_KEY", raising=False)
    base_config.production = True
    base_config.modules = {
        "judge": ModuleSlotConfig(model="x", api_key_env="MISSING_KEY"),
    }
    result = ModuleRegistry(base_config).validate()
    assert not result.valid
    assert any("MISSING_KEY" in e for e in result.errors)
