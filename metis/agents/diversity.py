"""Council/MoA diversity enforcement — heterogeneous agents required.

Research: Yang et al. (2026) arXiv:2602.03794 show homogeneous agent scaling
saturates; >=2 diverse models can match 16 homogeneous on vote/debate benchmarks.
Li et al. (2025) arXiv:2502.00674 caution that synthesis MoA may prefer one strong model.

Diversity is counted at two levels. A (model, endpoint) pair is the old unit, and it is
too fine: `qwen3-max`, `qwen3-32b` and `qwen3:8b` are three "unique models" from one
lab, trained on one corpus, sharing one set of blind spots. The VENDOR is the unit that
matters for independence, so the checks here also count vendors (`vendor_of`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from metis.config import ModelSlot

# Gateway prefixes are the vendor's own org name on OpenRouter/HF, and several vendors
# publish under more than one. Folded to one canonical name so `z-ai/glm-5.3` and a
# direct `glm-5.3` are the same vendor, and so are `meta-llama/…` and `llama-…`.
_VENDOR_ALIASES = {
    "z-ai": "zhipu", "zai": "zhipu", "zai-org": "zhipu", "thudm": "zhipu",
    "meta-llama": "meta", "facebook": "meta",
    "x-ai": "xai",
    "mistralai": "mistral",
    "moonshotai": "moonshot",
    "qwen": "alibaba",
    "deepseek-ai": "deepseek",
    "minimaxai": "minimax",
    "xiaomimimo": "xiaomi",
}

# Unprefixed ids (a vendor's own endpoint, Ollama tags) name the family, not the vendor.
# Most-specific first; matched as a prefix of the bare model name.
_FAMILY_VENDORS: Tuple[Tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gpt-", "openai"), ("chatgpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
    ("gemini", "google"), ("gemma", "google"),
    ("grok", "xai"),
    ("deepseek", "deepseek"),
    ("qwen", "alibaba"), ("qwq", "alibaba"),
    ("kimi", "moonshot"), ("moonshot", "moonshot"),
    ("minimax", "minimax"),
    ("glm", "zhipu"), ("chatglm", "zhipu"),
    ("llama", "meta"),
    ("mistral", "mistral"), ("mixtral", "mistral"), ("ministral", "mistral"),
    ("codestral", "mistral"), ("magistral", "mistral"),
    ("mimo", "xiaomi"),
    ("nemotron", "nvidia"),
    ("phi-", "microsoft"),
    ("command", "cohere"),
)


def vendor_of(model: str) -> str:
    """The lab that made `model`, as one canonical lowercase name.

    `vendor/model` → the prefix (canonicalised); a bare id → its family's vendor; an id
    nobody recognises → its own bare name, so two unknown models only count as one vendor
    when they are the same model. Never empty.
    """
    m = (model or "").strip().lower()
    if "/" in m:
        prefix = m.split("/", 1)[0].strip()
        if prefix:
            return _VENDOR_ALIASES.get(prefix, prefix)
        m = m.split("/", 1)[1]
    name = m.split(":", 1)[0]
    for family, vendor in _FAMILY_VENDORS:
        if name.startswith(family):
            return vendor
    return name or "unknown"


@dataclass
class DiversityReport:
    is_heterogeneous: bool
    unique_models: int
    warnings: List[str]
    unique_vendors: int = 0


def check_council_diversity(
    slots: List[ModelSlot],
    *,
    enforce: bool = True,
    min_unique_models: int = 2,
    min_unique_vendors: int = 1,
    label: str = "council",
) -> DiversityReport:
    """
    Reject homogeneous councils where all agents share the same model+base_url — or,
    with `min_unique_vendors` > 1, where they all come from too few vendors.

    When enforce=False, returns warnings only (likely win, not guaranteed).
    When enforce=True and the set is not heterogeneous, raises ValueError.

    See Yang et al. (2026) arXiv:2602.03794 — diversity over homogeneous scale.
    """
    if not slots:
        return DiversityReport(False, 0, [f"No {label} models configured"])

    signatures = {(s.model, s.base_url) for s in slots}
    vendors = {vendor_of(s.model) for s in slots}
    warnings: List[str] = []

    if len(signatures) < min_unique_models:
        warnings.append(
            f"Only {len(signatures)} unique model(s) in {label}; "
            f"ensemble diversity requires >= {min_unique_models}. "
            "Configure council_models with different models for reliable MoA gains."
        )
    if len(vendors) < min_unique_vendors:
        warnings.append(
            f"Only {len(vendors)} vendor(s) in {label} ({', '.join(sorted(vendors))}); "
            f"independence requires >= {min_unique_vendors}. Models from one lab share "
            "training data and blind spots, so they are not independent voices."
        )

    # Same model + same temperature spread is weak diversity
    temps = [s.temperature for s in slots]
    if len(signatures) == 1 and max(temps) - min(temps) < 0.15:
        warnings.append("Temperature spread too narrow for meaningful role diversity on a single model.")

    is_heterogeneous = len(signatures) >= min_unique_models and len(vendors) >= min_unique_vendors

    if enforce and not is_heterogeneous:
        raise ValueError("; ".join(warnings))

    return DiversityReport(is_heterogeneous, len(signatures), warnings, len(vendors))


def diversify_temperatures(slots: List[ModelSlot]) -> List[ModelSlot]:
    """Spread temperatures when models are homogeneous (fallback, weaker than true diversity)."""
    if len({s.model for s in slots}) > 1:
        return slots
    spread = [0.3, 0.5, 0.7, 0.85, 0.95]
    out: List[ModelSlot] = []
    for i, slot in enumerate(slots):
        copy = slot.model_copy()
        copy.temperature = spread[i % len(spread)]
        out.append(copy)
    return out
