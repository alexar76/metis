"""Council/MoA diversity enforcement — heterogeneous agents required.

Research: Yang et al. (2026) arXiv:2602.03794 show homogeneous agent scaling
saturates; >=2 diverse models can match 16 homogeneous on vote/debate benchmarks.
Li et al. (2025) arXiv:2502.00674 caution that synthesis MoA may prefer one strong model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from metis.config import ModelSlot


@dataclass
class DiversityReport:
    is_heterogeneous: bool
    unique_models: int
    warnings: List[str]


def check_council_diversity(
    slots: List[ModelSlot],
    *,
    enforce: bool = True,
    min_unique_models: int = 2,
) -> DiversityReport:
    """
    Reject homogeneous councils where all agents share the same model+base_url.

    When enforce=False, returns warnings only (likely win, not guaranteed).
    When enforce=True and only one unique model, raises ValueError.

    See Yang et al. (2026) arXiv:2602.03794 — diversity over homogeneous scale.
    """
    if not slots:
        return DiversityReport(False, 0, ["No council models configured"])

    signatures = {(s.model, s.base_url) for s in slots}
    warnings: List[str] = []

    if len(signatures) < min_unique_models:
        warnings.append(
            f"Only {len(signatures)} unique model(s) in council; "
            f"ensemble diversity requires >= {min_unique_models}. "
            "Configure council_models with different models for reliable MoA gains."
        )

    # Same model + same temperature spread is weak diversity
    temps = [s.temperature for s in slots]
    if len(signatures) == 1 and max(temps) - min(temps) < 0.15:
        warnings.append("Temperature spread too narrow for meaningful role diversity on a single model.")

    is_heterogeneous = len(signatures) >= min_unique_models

    if enforce and not is_heterogeneous:
        raise ValueError("; ".join(warnings))

    return DiversityReport(is_heterogeneous, len(signatures), warnings)


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
