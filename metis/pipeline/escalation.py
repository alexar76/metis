"""Escalation logic between DGPD depth levels."""

from __future__ import annotations

from metis.config import RuntimeConfig
from metis.pipeline.depth import DepthLevel


class EscalationPolicy:
    """Decide when to escalate pipeline depth."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.threshold = config.dgpd.agreement_threshold

    def after_l1_consensus(self, agreement: float) -> DepthLevel:
        if agreement >= self.threshold:
            return DepthLevel.L1_QUICK_CONSENSUS
        return DepthLevel.L2_STANDARD

    def after_l2_proposers(self, agreement: float) -> DepthLevel:
        if agreement >= self.threshold:
            return DepthLevel.L2_STANDARD
        return DepthLevel.L3_FULL

    def max_retries_for_depth(self, depth: DepthLevel) -> int:
        if depth == DepthLevel.L3_FULL:
            return 3
        if depth == DepthLevel.L2_STANDARD:
            return 1
        return 0


def should_escalate(agreement: float, threshold: float) -> bool:
    return agreement < threshold
