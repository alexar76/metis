"""Pipeline depth and agreement scoring (DGPD)."""

from metis.pipeline.agreement import compute_agreement, compute_proposer_agreement
from metis.pipeline.depth import DepthGate, DepthLevel, requires_full_depth
from metis.pipeline.escalation import EscalationPolicy, should_escalate

__all__ = [
    "DepthLevel",
    "DepthGate",
    "requires_full_depth",
    "compute_agreement",
    "compute_proposer_agreement",
    "EscalationPolicy",
    "should_escalate",
]
