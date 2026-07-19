"""Multimodal: image validation (SSRF/injection), extraction, and the vision→council path."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from metis.api.app import create_app
from metis.api.bridge import extract_images
from metis.config import ProviderKind, RouteMode, RuntimeConfig
from metis.exoskeleton import Metis
from metis.models.provider import model_supports_vision
from metis.security.media import validate_image_url, validate_images

# a real 1×1 png data URI
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
       "QVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


# ── URL validation / SSRF / injection transport ──────────────────────────────

def test_validate_data_image_ok():
    assert validate_image_url(PNG) == PNG


def test_reject_non_image_data_uri():
    with pytest.raises(ValueError):
        validate_image_url("data:text/html;base64,PHNjcmlwdD4=")


def test_reject_localhost_ssrf():
    with pytest.raises(ValueError):
        validate_image_url("http://localhost/x.png")
    with pytest.raises(ValueError):
        validate_image_url("http://169.254.169.254/latest/meta-data/")


def test_accept_public_https():
    assert validate_image_url("https://example.com/a.png").startswith("https://")


def test_validate_images_caps_and_drops_invalid():
    # distinct valid data URIs (transport layer doesn't parse base64) to hit the cap
    distinct = [PNG + ("A" * i) for i in range(8)]
    urls = distinct[:2] + ["http://localhost/x", PNG, PNG] + distinct[2:]  # + dupes + SSRF
    out = validate_images(urls, max_images=5)
    assert len(out) == 5  # capped
    assert "http://localhost/x" not in out  # SSRF dropped
    assert len(set(out)) == len(out)  # de-duped


# ── extraction from OpenAI multimodal messages ───────────────────────────────

def test_extract_images_from_messages():
    msgs = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image_url", "image_url": {"url": PNG}},
            {"type": "image_url", "image_url": {"url": "http://127.0.0.1/secret.png"}},
        ],
    }]
    imgs = extract_images(msgs, 5)
    assert imgs == [PNG]  # private host dropped


# ── vision detection ─────────────────────────────────────────────────────────

def test_model_supports_vision_heuristic():
    from metis.config import ModelSlot
    assert model_supports_vision(ModelSlot(name="b", model="qwen2-vl:7b"))
    assert model_supports_vision(ModelSlot(name="b", model="gpt-4o"))
    assert not model_supports_vision(ModelSlot(name="b", model="qwen3:8b"))
    assert model_supports_vision(ModelSlot(name="b", model="qwen3:8b", supports_vision=True))


# ── vision→council path ──────────────────────────────────────────────────────

@pytest.fixture
def vision_cfg(tmp_path):
    return RuntimeConfig(
        provider=ProviderKind.MOCK, allow_test_provider=True,
        base_model="qwen2-vl",  # vision-capable name → resolve_vision_slot finds it
        memory_dir=tmp_path / "m", thinking_samples=1, enable_multimodal=True,
    )


async def test_run_with_image_uses_vision(vision_cfg):
    brain = Metis(vision_cfg)
    res = await brain.run("What is in this image?", route=RouteMode.FAST, images=[PNG])
    assert res.metadata.get("multimodal") is True
    assert res.metadata.get("images") == 1
    assert res.metadata.get("vision_model") == "qwen2-vl"
    assert res.answer  # produced an answer using the observation


async def test_run_without_vision_flags_unsupported(tmp_path):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK, allow_test_provider=True,
        base_model="qwen3:8b",  # NOT vision-capable
        memory_dir=tmp_path / "m", thinking_samples=1, enable_multimodal=True,
    )
    brain = Metis(cfg)
    res = await brain.run("Describe it", route=RouteMode.FAST, images=[PNG])
    assert res.metadata.get("multimodal_unsupported") is True
    assert res.answer  # still answers on text, image not honoured as instructions


def test_chat_completions_accepts_images(tmp_path):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK, allow_test_provider=True, base_model="llava",
        memory_dir=tmp_path / "m", thinking_samples=1,
    )
    client = TestClient(create_app(cfg))
    r = client.post("/v1/chat/completions", json={
        "model": "metis-fast",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image_url", "image_url": {"url": PNG}},
        ]}],
    })
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"]


# ── per-slot vision provider wiring (e.g. OpenRouter free VL model) ───────────

def test_vision_module_slot_resolves_with_headers():
    """A modules.vision entry (own provider/model/key/headers) drives perception."""
    from metis.config import ModuleSlotConfig
    from metis.modules.registry import resolve_vision_slot
    from metis.models.provider import OpenAICompatProvider

    cfg = RuntimeConfig(provider=ProviderKind.MOCK, allow_test_provider=True, base_model="qwen3:8b")
    cfg.modules["vision"] = ModuleSlotConfig(
        provider=ProviderKind.OPENAI_COMPAT,
        model="nvidia/nemotron-nano-12b-v2-vl:free",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        extra_headers={"HTTP-Referer": "https://metis.modelmarket.dev", "X-Title": "Metis"},
    )
    slot = resolve_vision_slot(cfg)
    assert slot is not None and slot.model.endswith(":free")
    assert model_supports_vision(slot) is True          # "-vl" name → vision-capable
    assert slot.extra_headers["X-Title"] == "Metis"
    # headers land on the HTTP client (OpenRouter free-tier priority)
    p = OpenAICompatProvider(slot)
    hdrs = {k.lower() for k in p._client.headers}
    assert "http-referer" in hdrs and "x-title" in hdrs


async def test_perceive_times_out_failsafe(tmp_path, monkeypatch):
    """A slow/hung vision model must fail over to text with an honest note."""
    import asyncio
    from metis.config import ModuleSlotConfig

    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK, allow_test_provider=True, base_model="qwen3:8b",
        memory_dir=tmp_path / "m", thinking_samples=1, enable_multimodal=True,
        vision_timeout_seconds=1.5, vision_retries=2,
    )
    cfg.modules["vision"] = ModuleSlotConfig(
        provider=ProviderKind.MOCK, model="mock-vl", api_key="x",
    )
    brain = Metis(cfg)

    async def _hang(*a, **k):
        await asyncio.sleep(5)
        return "should never arrive"

    monkeypatch.setattr("tests.support.mock_provider.MockProvider.complete_multimodal", _hang, raising=False)
    obs, meta = await brain._perceive([PNG], "what is this?")
    assert meta["multimodal"] is False
    assert "vision_error" in meta            # timed out → fail-safe
    assert "could not be read" in obs or "could not be reached" in obs


def test_observability_handles_multimodal_content():
    """The observability wrapper must not choke on list (multimodal) content —
    this was why vision crashed through ObservedProvider ('list' has no 'encode')."""
    from metis.observability.logging.tracer import (
        summarize_content, summarize_messages, _stringify_content,
    )
    from metis.models.provider import Message
    parts = [
        {"type": "text", "text": "what number is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]
    flat = _stringify_content(parts)
    assert "[image]" in flat and "what number" in flat
    assert "QUJD" not in flat                       # never leak/log the base64 payload
    s = summarize_content(parts)                    # must NOT raise
    assert s["length"] > 0
    m = summarize_messages([Message("system", "s"), Message("user", parts)])  # must NOT raise
    assert m["message_count"] == 2
