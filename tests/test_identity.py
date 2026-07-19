"""Operator identity/self-knowledge injection (reaches every route via the provider layer)."""

from __future__ import annotations

from metis.config import ProviderKind, RuntimeConfig
from metis.models.provider import (
    LLMProvider, LLMResponse, Message, _IdentityProvider, create_provider,
)


class _Rec(LLMProvider):
    def __init__(self):
        self.seen = None

    async def complete(self, messages, *, temperature=None, max_tokens=None):
        self.seen = list(messages)
        return LLMResponse(content="ok", model="rec")


async def test_identity_prepended_to_existing_system():
    rec = _Rec()
    p = _IdentityProvider(rec, "I am Metis.")
    await p.complete([Message("system", "Base rules."), Message("user", "hi")])
    assert rec.seen[0].role == "system"
    assert rec.seen[0].content.startswith("I am Metis.")
    assert "Base rules." in rec.seen[0].content
    assert rec.seen[1].role == "user"


async def test_identity_inserted_when_no_system():
    rec = _Rec()
    await _IdentityProvider(rec, "I am Metis.").complete([Message("user", "hi")])
    assert rec.seen[0].role == "system" and rec.seen[0].content == "I am Metis."


async def test_empty_identity_is_passthrough():
    rec = _Rec()
    await _IdentityProvider(rec, "   ").complete([Message("user", "hi")])
    assert len(rec.seen) == 1 and rec.seen[0].role == "user"


async def test_identity_reaches_complete_text_and_multimodal():
    rec = _Rec()
    p = _IdentityProvider(rec, "ID-BLOCK")
    await p.complete_text("SysPrompt", "User")           # text route
    assert rec.seen[0].content.startswith("ID-BLOCK") and "SysPrompt" in rec.seen[0].content
    rec2 = _Rec()
    p2 = _IdentityProvider(rec2, "ID-BLOCK")
    await p2.complete_multimodal("VisionSys", "what?", ["data:image/png;base64,QUJD"])  # vision route
    assert rec2.seen[0].role == "system" and rec2.seen[0].content.startswith("ID-BLOCK")
    assert isinstance(rec2.seen[1].content, list)         # image parts preserved untouched


def test_create_provider_wraps_only_answer_roles_when_identity_set():
    from metis.config import ModelSlot
    cfg = RuntimeConfig(provider=ProviderKind.OPENAI_COMPAT, base_model="deepseek-chat",
                        identity="You are Metis, the cognition tier.")
    # answer roles get identity (base/agent + the council's FINAL aggregator) …
    for role in ("base", "agent", "moa_aggregator"):
        slot = cfg.base_slot() if role == "base" else ModelSlot(name=role, model="deepseek-chat")
        assert isinstance(create_provider(slot, cfg), _IdentityProvider), role
    # … internal structured/scoring AND the intermediate MoA prose roles do NOT
    # (proposers/refiner mimicking structured output leaked JSON into answers)
    for role in ("synthesizer", "intent_parser_a", "constraint_extractor", "judge",
                 "router", "moa_proposer_logician", "moa_refiner"):
        slot = ModelSlot(name=role, model="deepseek-chat")
        assert not isinstance(create_provider(slot, cfg), _IdentityProvider), role
    # no identity set → never wrapped
    cfg2 = RuntimeConfig(provider=ProviderKind.OPENAI_COMPAT, base_model="deepseek-chat")
    assert not isinstance(create_provider(cfg2.base_slot(), cfg2), _IdentityProvider)


def test_spec_leak_detector():
    """The output guard flags leaked TaskSpec/JSON blobs, not legit answers/code."""
    from metis.exoskeleton import _looks_like_spec_leak
    assert _looks_like_spec_leak('{"goal":"x","constraints":["a"],"non_goals":["b"]}')
    assert _looks_like_spec_leak('```json\n{"constraints":[],"goal":"y","non_goals":[]}\n```')
    assert not _looks_like_spec_leak("Metis is a cognitive layer that deliberates and verifies.")
    assert not _looks_like_spec_leak('```python\nprint(1)\n```')       # legit code answer
    assert not _looks_like_spec_leak('{"answer": 42}')                  # a small JSON, not a spec
    assert not _looks_like_spec_leak("")
