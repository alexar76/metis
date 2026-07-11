"""Benchmark model providers — DeepSeek, OpenAI, Ollama."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from metis.config import ProviderKind


@dataclass(frozen=True)
class ModelSpec:
    """Resolved model endpoint for benchmarks."""

    name: str
    model: str
    provider: ProviderKind
    base_url: str
    api_key: str
    input_per_1m: float = 0.0
    output_per_1m: float = 0.0
    provider_label: str = "unknown"
    requires_key: bool = False


# Default pricing hints for cost comparison (USD per 1M tokens).
_CATALOG: Dict[str, Dict[str, object]] = {
    "deepseek-chat": {
        "model": "deepseek-chat",
        "provider": ProviderKind.OPENAI_COMPAT,
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "input_per_1m": 0.27,
        "output_per_1m": 1.10,
        "provider_label": "deepseek",
        "requires_key": True,
    },
    "gpt-4o-mini": {
        "model": "gpt-4o-mini",
        "provider": ProviderKind.OPENAI_COMPAT,
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
        "provider_label": "openai",
        "requires_key": True,
    },
    "qwen3:8b": {
        "model": "qwen3:8b",
        "provider": ProviderKind.OLLAMA,
        "base_url": "http://localhost:11434/v1",
        "env_key": None,
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "provider_label": "local",
        "requires_key": False,
    },
}


def _env_key(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    value = os.environ.get(name, "").strip()
    return value or None


def resolve_model_spec(model_name: str) -> Optional[ModelSpec]:
    """Resolve a catalog or raw model name; return None if API key missing."""
    entry = _CATALOG.get(model_name)
    if entry:
        env_var = entry.get("env_key")
        api_key = _env_key(env_var) if env_var else "ollama"
        if entry.get("requires_key") and not api_key:
            return None
        return ModelSpec(
            name=model_name,
            model=str(entry["model"]),
            provider=entry["provider"],  # type: ignore[arg-type]
            base_url=str(entry["base_url"]),
            api_key=api_key or "ollama",
            input_per_1m=float(entry.get("input_per_1m", 0.0)),
            output_per_1m=float(entry.get("output_per_1m", 0.0)),
            provider_label=str(entry.get("provider_label", "unknown")),
            requires_key=bool(entry.get("requires_key")),
        )

    # Ad-hoc model id: try OpenAI-compat with METIS_* or OPENAI_API_KEY.
    api_key = _env_key("OPENAI_API_KEY") or _env_key("METIS_API_KEY") or _env_key("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    base_url = os.environ.get("METIS_BASE_URL", "https://api.openai.com/v1")
    return ModelSpec(
        name=model_name,
        model=model_name,
        provider=ProviderKind.OPENAI_COMPAT,
        base_url=base_url,
        api_key=api_key,
        provider_label="custom",
        requires_key=True,
    )


def available_models(include_without_keys: bool = False) -> List[str]:
    """List models that can run (have keys when required)."""
    names: List[str] = []
    for name, entry in _CATALOG.items():
        if entry.get("requires_key") and not _env_key(entry.get("env_key")):  # type: ignore[arg-type]
            if include_without_keys:
                names.append(name)
            continue
        names.append(name)
    return names


def skipped_models(requested: List[str]) -> List[str]:
    """Models requested but unavailable due to missing credentials."""
    skipped: List[str] = []
    for name in requested:
        if resolve_model_spec(name) is None:
            skipped.append(name)
    return skipped
