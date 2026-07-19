"""Pipeline depth levels and DGPD gating."""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional, Tuple

from metis.config import RouteMode, RuntimeConfig
from metis.schemas.task_spec import TaskSpec
from metis.security.injection import sanitize_user_input


class DepthLevel(str, Enum):
    L0_FAST = "L0"
    L1_QUICK_CONSENSUS = "L1"
    L2_STANDARD = "L2"
    L3_FULL = "L3"


DEPTH_BASELINE_CALLS = {
    DepthLevel.L0_FAST: 1,
    DepthLevel.L1_QUICK_CONSENSUS: 4,
    DepthLevel.L2_STANDARD: 8,
    DepthLevel.L3_FULL: 14,
}

_FULL_DEPTH_BASELINE = DEPTH_BASELINE_CALLS[DepthLevel.L3_FULL]

_CODE_PATTERNS = re.compile(
    r"\b(run code|execute|python|bash|shell|delete file|rm -rf|eval\()\b",
    re.I,
)
_SENSITIVE_PATTERNS = re.compile(
    r"\b(password|api[_-]?key|secret|token|credential|private key)\b",
    re.I,
)


class DepthGate:
    """Select initial pipeline depth; security gates are never skipped."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def sanitize_and_gate(self, query: str) -> Tuple[str, DepthLevel, Optional[str]]:
        """Return (sanitized_query, depth, security_reason)."""
        result = sanitize_user_input(query, max_length=self.config.security.max_user_input_chars)
        sanitized = result.text

        if result.injection_detected and self.config.security.enforce_injection_scan:
            return sanitized, DepthLevel.L3_FULL, "injection_detected"

        if _CODE_PATTERNS.search(sanitized):
            return sanitized, DepthLevel.L3_FULL, "code_execution"

        if _SENSITIVE_PATTERNS.search(sanitized):
            return sanitized, DepthLevel.L3_FULL, "sensitive_keywords"

        if not self.config.dgpd.enabled:
            return sanitized, DepthLevel.L3_FULL, None

        return sanitized, DepthLevel.L1_QUICK_CONSENSUS, None

    def initial_from_route(self, route: RouteMode, spec: TaskSpec) -> DepthLevel:
        if not self.config.dgpd.enabled:
            return DepthLevel.L3_FULL

        query = spec.goal.lower()
        has_tool_markers = bool(
            re.search(r"\b(search|browse|run code|execute|tool|api|file)\b", query)
        )

        if route == RouteMode.FAST and not spec.requires_tools and not has_tool_markers:
            if not spec.ambiguities and len(query.split()) < 15:
                return DepthLevel.L0_FAST

        if route in (RouteMode.AGENT, RouteMode.COUNCIL):
            return DepthLevel.L3_FULL

        return DepthLevel.L1_QUICK_CONSENSUS

    @staticmethod
    def calls_saved(chosen: DepthLevel) -> int:
        return max(0, _FULL_DEPTH_BASELINE - DEPTH_BASELINE_CALLS.get(chosen, _FULL_DEPTH_BASELINE))


def requires_full_depth(query: str, config: RuntimeConfig) -> bool:
    lower = query.lower()
    for kw in config.dgpd.force_full_depth_keywords:
        if kw.lower() in lower:
            return True
    if _CODE_PATTERNS.search(query):
        return True
    if _SENSITIVE_PATTERNS.search(query):
        return True
    return False
