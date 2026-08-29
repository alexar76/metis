"""The base slot's key: the environment first, never a silent "ollama".

Found live: prod.yaml carried an `api_key_env: OPENROUTER_API_KEY` line the top level did not
support — so it was ignored — plus a pasted DeepSeek key pointed at openrouter.ai. Modules
with their own `api_key_env` worked; everything that fell through to the base slot answered
401. /health stayed green and not one completion succeeded.
"""

from __future__ import annotations

import pytest



def _config(**kw):
    from metis.config import RuntimeConfig

    return RuntimeConfig(**kw)


def test_the_environment_wins_over_a_literal(monkeypatch):
    monkeypatch.setenv("SOME_PROVIDER_KEY", "sk-from-env")
    c = _config(api_key="sk-pasted-in-yaml", api_key_env="SOME_PROVIDER_KEY")
    assert c.resolved_api_key() == "sk-from-env"


def test_an_empty_named_variable_says_so_and_falls_back(monkeypatch, caplog):
    import logging

    monkeypatch.delenv("SOME_PROVIDER_KEY", raising=False)
    c = _config(api_key="sk-pasted-in-yaml", api_key_env="SOME_PROVIDER_KEY")
    with caplog.at_level(logging.ERROR):
        assert c.resolved_api_key() == "sk-pasted-in-yaml"
    assert "api_key_env" in caplog.text


def test_without_api_key_env_the_literal_is_used():
    c = _config(api_key="sk-pasted-in-yaml")
    assert c.resolved_api_key() == "sk-pasted-in-yaml"


def test_the_inbound_service_token_is_not_the_provider_key(monkeypatch):
    """`METIS_API_KEY` is the token CLIENTS present. Because settings carry `env_prefix="METIS_"`,
    it also lands in `api_key` — the key METIS presents to the model provider. Two different
    secrets on one name, and on the live host the service token was being sent to
    openrouter.ai, which answered 401 for every module that used the base slot.

    Naming the provider variable explicitly is what breaks the collision.
    """
    monkeypatch.setenv("METIS_API_KEY", "metis-inbound-service-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-the-real-one")

    collided = _config()
    assert collided.resolved_api_key() == "metis-inbound-service-token", (
        "this is the trap, pinned so the fix below is not mistaken for cosmetics")

    fixed = _config(api_key_env="OPENROUTER_API_KEY")
    assert fixed.resolved_api_key() == "sk-or-the-real-one"


def test_the_base_slot_uses_the_resolved_key(monkeypatch):
    monkeypatch.setenv("SOME_PROVIDER_KEY", "sk-from-env")
    c = _config(api_key="sk-pasted-in-yaml", api_key_env="SOME_PROVIDER_KEY")
    slot = c.base_slot() if callable(getattr(c, "base_slot", None)) else None
    if slot is None:
        pytest.skip("base_slot is not a method on this build")
    assert slot.api_key == "sk-from-env"
