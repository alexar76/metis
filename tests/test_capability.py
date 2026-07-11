"""Capability gate: a weak model must lose its vote where it can do harm.

Backs the measured finding (docs/benchmarks/): a weak aggregator dragged a Llama+Qwen
council below Qwen alone. The gate must (a) put the strongest model in the aggregator/
verifier/synthesizer seats and (b) strip below-floor models of their proposer vote — while
never emptying a role and staying a no-op for single-model setups.
"""
from __future__ import annotations

from metis.config import ModelSlot, ModuleSlotConfig, ProviderKind, RuntimeConfig
from metis.modules.registry import ModuleRegistry
from metis.agents import capability as cap


def _slot(model, name="x"):
    return ModelSlot(name=name, provider=ProviderKind.OPENAI_COMPAT, model=model,
                     base_url="https://x/v1", api_key="k")


# --- capability lookup -----------------------------------------------------------------

def test_capability_lookup_known_fuzzy_default():
    assert cap.capability_of("deepseek-v4-pro") == 97.0
    assert cap.capability_of("moonshotai/kimi-k2.6") == 90.0      # provider prefix stripped
    assert cap.capability_of("nvidia/nemotron-nano-12b-v2-vl:free") == 44.0  # ":free" stripped
    assert cap.capability_of("some-unknown-model-xyz") == cap.DEFAULT_CAPABILITY
    assert cap.tier_of(cap.capability_of("llama-3.1-8b-instruct")) == cap.Tier.WEAK
    assert cap.tier_of(cap.capability_of("deepseek-v4-pro")) == cap.Tier.FRONTIER


# --- gate_role unit behaviour ----------------------------------------------------------

def test_high_leverage_roles_get_the_strongest():
    pool = [_slot("llama-3.1-8b-instruct"), _slot("qwen3-max")]  # 55 vs 92
    for role in ("moa_aggregator", "judge", "synthesizer"):
        got = cap.gate_role(role, _slot("llama-3.1-8b-instruct", role), pool, floor=60, min_aggregator=75)
        assert got.model == "qwen3-max", role


def test_weak_proposer_loses_its_vote():
    pool = [_slot("llama-3.1-8b-instruct"), _slot("qwen-2.5-7b-instruct")]  # 55 vs 63, floor 60
    got = cap.gate_role("moa_proposer_logician", _slot("llama-3.1-8b-instruct", "moa_proposer_logician"),
                        pool, floor=60, min_aggregator=75)
    assert got.model == "qwen-2.5-7b-instruct"   # below-floor Llama swapped out
    assert cap.capability_of(got.model) >= 60


def test_floor_passing_proposer_is_kept():
    pool = [_slot("qwen-2.5-7b-instruct"), _slot("qwen3-max")]
    got = cap.gate_role("moa_proposer_skeptic", _slot("qwen-2.5-7b-instruct", "moa_proposer_skeptic"),
                        pool, floor=60, min_aggregator=75)
    assert got.model == "qwen-2.5-7b-instruct"   # 63 >= 60 → untouched


def test_vision_and_router_never_gated():
    pool = [_slot("qwen3-max"), _slot("nvidia/nemotron-nano-12b-v2-vl:free")]
    v = cap.gate_role("vision", _slot("nvidia/nemotron-nano-12b-v2-vl:free", "vision"), pool, 60, 75)
    assert "nemotron" in v.model               # vision keeps its VL model, not swapped to qwen3-max
    r = cap.gate_role("router", _slot("llama-3.1-8b-instruct", "router"), pool, 60, 75)
    assert r.model == "llama-3.1-8b-instruct"   # cheap router left alone


def test_single_model_is_a_noop():
    pool = [_slot("deepseek-v4-pro")]
    for role in ("moa_aggregator", "judge", "moa_proposer_logician", "intent_parser_a"):
        got = cap.gate_role(role, _slot("deepseek-v4-pro", role), pool, floor=60, min_aggregator=75)
        assert got.model == "deepseek-v4-pro"   # only model → never emptied, never changed


def test_all_below_floor_falls_back_to_strongest_never_empty():
    pool = [_slot("llama-3.1-8b-instruct"), _slot("llama-3.2-3b-instruct")]  # 55, 40 — both < floor
    got = cap.gate_role("moa_proposer_logician", _slot("llama-3.2-3b-instruct", "moa_proposer_logician"),
                        pool, floor=60, min_aggregator=75)
    assert got.model == "llama-3.1-8b-instruct"  # best available, not empty


# --- end-to-end through the registry ---------------------------------------------------

def _weak_config():
    return RuntimeConfig(
        provider=ProviderKind.OPENAI_COMPAT, base_model="llama-3.1-8b-instruct",
        base_url="https://x/v1", api_key="k", enforce_capability_gate=True,
        council_capability_floor=60.0, min_aggregator_capability=75.0,
        modules={
            "moa_proposer_logician": ModuleSlotConfig(model="qwen-2.5-7b-instruct"),
            "intent_parser_a": ModuleSlotConfig(model="qwen3-max"),
        },
    )


def test_registry_gating_end_to_end():
    reg = ModuleRegistry(_weak_config())
    # pool = {llama-3.1-8b (55), qwen-2.5-7b (63), qwen3-max (92)}; strongest = qwen3-max
    assert reg.resolve_slot("moa_aggregator").model == "qwen3-max"
    assert reg.resolve_slot("judge").model == "qwen3-max"          # verifier
    assert reg.resolve_slot("synthesizer").model == "qwen3-max"
    # a proposer that would fall back to base (Llama, below floor) is NOT Llama anymore
    assert reg.resolve_slot("moa_proposer_skeptic").model != "llama-3.1-8b-instruct"
    # a floor-passing configured proposer keeps its own model
    assert reg.resolve_slot("moa_proposer_logician").model == "qwen-2.5-7b-instruct"
    # Llama is reported as excluded from the council
    assert "llama-3.1-8b-instruct" in cap.excluded_from_council(reg._reasoning_pool(), 60.0)


def test_registry_gate_off_keeps_weak_base():
    cfg = _weak_config(); cfg.enforce_capability_gate = False
    reg = ModuleRegistry(cfg)
    # with the gate off, the weak base model serves the aggregator (the old, risky behaviour)
    assert reg.resolve_slot("moa_aggregator").model == "llama-3.1-8b-instruct"


def test_top_frontier_lab_models_are_frontier_tier():
    """Anthropic/OpenAI/Google/xAI flagships must rank frontier so they win high-leverage
    seats when configured (provider prefixes stripped)."""
    for m in ("anthropic/claude-opus-4.8", "openai/gpt-5.5", "google/gemini-3.1-pro", "x-ai/grok-4.5"):
        assert cap.tier_of(cap.capability_of(m)) == cap.Tier.FRONTIER, m
    # a frontier lab model beats a strong open model for the aggregator seat
    pool = [_slot("qwen3-max"), _slot("anthropic/claude-opus-4.8")]
    got = cap.gate_role("moa_aggregator", _slot("qwen3-max", "moa_aggregator"), pool, 60, 75)
    assert "claude-opus-4.8" in got.model


def test_family_priors_survive_version_drift():
    """A new release in a known frontier family ranks high without being listed/calibrated."""
    assert cap.capability_of("openai/gpt-5.7") >= 90          # gpt-5 family
    assert cap.capability_of("anthropic/claude-opus-4.9") >= 90
    assert cap.capability_of("x-ai/grok-4.7") >= 85
    assert cap.capability_of("google/gemini-4-pro") >= 80     # frontier-adjacent fallback
    assert cap.capability_of("acme/frobnicator-1") == cap.DEFAULT_CAPABILITY  # truly unknown → mid
    # current-as-of-2026-07 flagships resolve correctly
    assert cap.capability_of("openai/gpt-5.6") == 97.0
    assert cap.tier_of(cap.capability_of("google/gemini-3.1-pro")) == cap.Tier.FRONTIER
