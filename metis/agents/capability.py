"""Relative model-capability registry + council role-gating.

Motivation (measured, see docs/benchmarks/HEAD-TO-HEAD-2026-07-11.md): a weak model in a
high-leverage seat drags the whole council *below* its strongest member — a Llama-3.1-8B
aggregator pulled a Llama+Qwen council to 60%, under Qwen-7B's own 90%. So a randomly
plugged-in weak model must not get a vote where it can do harm.

Policy:
  * the high-leverage roles — aggregator, verifier (judge), final synthesizer — always go
    to the STRONGEST configured model (that is where answer quality concentrates);
  * models below a capability floor lose their vote as proposers/parsers (swapped for the
    best floor-passing model), so a dumb voice can't sway the consensus;
  * roles that need a *specific* capability (vision) or are deliberately cheap (router) are
    never gated.
The gate is a no-op for a single-model deployment (the one model is both strongest and
above the floor), so it only ever helps.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from metis.config import ModelSlot

# 0..100 capability priors — seeded from published leaderboards + our own live benchmarks
# (docs/benchmarks/). These are PRIORS used only to *rank* models for role-gating; run
# `metis calibrate` to override them with scores measured against your own endpoints.
DEFAULT_CAPABILITY = 65.0
MODEL_CAPABILITY: Dict[str, float] = {
    # --- frontier: Anthropic ---
    "claude-opus-4.8": 98.0, "claude-opus-4.7": 96.0, "claude-opus-4.6": 95.0,
    "claude-opus-4.5": 94.0, "claude-opus-4.1": 92.0, "claude-opus-4": 91.0,
    "claude-sonnet-5": 93.0, "claude-sonnet-4.5": 88.0, "claude-sonnet-4": 84.0,
    "claude-haiku-4.5": 80.0,
    # --- frontier: OpenAI (GPT-5.6 is current as of 2026-07; verified via web) ---
    "gpt-5.6": 97.0, "gpt-5.6-sol": 97.0, "gpt-5.6-terra": 90.0, "gpt-5.6-luna": 82.0,
    "gpt-5.5": 96.0, "gpt-5.5-fast": 90.0, "gpt-5": 94.0, "gpt-5-mini": 78.0,
    "o4": 93.0, "o3": 90.0, "o3-mini": 79.0,
    # --- frontier: Google (3.1 Pro top + 3.5 Flash current as of 2026-07; verified via web) ---
    "gemini-3.1-pro": 95.0, "gemini-3-pro": 93.0,
    "gemini-3.5-flash": 86.0, "gemini-3-flash": 82.0,
    "gemini-2.5-pro": 88.0, "gemini-2.5-flash": 76.0,
    # --- frontier: xAI (Grok) ---
    "grok-4.5": 92.0, "grok-4.3": 90.0, "grok-4.20": 91.0, "grok-4": 88.0,
    # --- frontier / strong: open + Chinese labs (tested live) ---
    "deepseek-v4-pro": 97.0, "deepseek-v4-flash": 84.0,
    "qwen3-max": 92.0, "qwen3-max-thinking": 93.0,
    "kimi-k2.6": 90.0, "kimi-k2-thinking": 91.0, "kimi-k2.5": 88.0,
    "minimax-m3": 90.0, "minimax-m2": 78.0,
    "glm-5.2": 88.0, "glm-5": 86.0, "glm-4.6": 82.0,
    "deepseek-chat": 80.0, "deepseek-v3.2": 80.0,
    # mid
    "qwen-2.5-7b-instruct": 63.0, "qwen2.5-7b-instruct": 63.0,
    "llama-3.3-70b-instruct": 70.0, "mixtral-8x7b-instruct": 60.0,
    # weak
    "llama-3.1-8b-instruct": 55.0, "llama-3.2-3b-instruct": 40.0,
    "nemotron-nano-9b-v2": 46.0, "nemotron-nano-12b-v2-vl": 44.0,
    "gemma-2-9b-it": 52.0, "ministral-8b": 54.0,
}


class Tier(str, Enum):
    FRONTIER = "frontier"
    STRONG = "strong"
    MID = "mid"
    WEAK = "weak"


def tier_of(score: float) -> Tier:
    if score >= 90:
        return Tier.FRONTIER
    if score >= 75:
        return Tier.STRONG
    if score >= 58:
        return Tier.MID
    return Tier.WEAK


def _normalize(model: str) -> str:
    m = (model or "").strip().lower()
    if "/" in m:            # drop provider prefix, e.g. "moonshotai/kimi-k2.6"
        m = m.split("/", 1)[1]
    m = m.split(":")[0]     # drop ":free" / ":nitro" suffix
    return m


# capability overrides loaded from `metis calibrate` (data/capability.json), keyed normalized
_CALIBRATED: Dict[str, float] = {}


def load_calibration(scores: Dict[str, float]) -> None:
    """Merge measured capability scores (from calibration) over the static priors."""
    _CALIBRATED.update({_normalize(k): float(v) for k, v in scores.items()})


# Family priors — version-drift fallback so a NEW release in a known frontier family
# (e.g. gpt-5.7, gemini-4-pro, claude-opus-4.9) gets a sensible frontier score instead of
# "unknown → mid", even before it's added above or calibrated. Most-specific prefix first.
FAMILY_PRIORS: List[tuple] = [
    ("gpt-5", 94.0), ("gpt-", 82.0), ("o4", 92.0), ("o3", 88.0),
    ("gemini-3", 90.0), ("gemini-2.5", 84.0), ("gemini-", 80.0),
    ("claude-opus", 94.0), ("claude-sonnet", 86.0), ("claude-haiku", 76.0), ("claude-", 85.0),
    ("grok-4", 88.0), ("grok-", 80.0),
    ("deepseek-v4", 90.0), ("deepseek-", 78.0),
    ("qwen3-max", 92.0), ("qwen3", 85.0), ("kimi-k2", 88.0), ("kimi", 84.0),
    ("glm-5", 85.0), ("glm-4", 80.0), ("minimax-m", 82.0),
    ("llama-3.1-8b", 55.0), ("llama-3.2", 42.0), ("llama-4", 78.0), ("llama-", 62.0),
]


def capability_of(model: str) -> float:
    """Relative capability (0..100).
    Calibrated score > exact prior > longest-prefix prior > frontier-family prior > default.
    """
    n = _normalize(model)
    table = {**MODEL_CAPABILITY, **_CALIBRATED}
    if n in table:
        return table[n]
    best: Optional[tuple] = None      # longest prefix match either direction
    for k, v in table.items():
        if n.startswith(k) or k.startswith(n):
            if best is None or len(k) > best[0]:
                best = (len(k), v)
    if best:
        return best[1]
    for prefix, score in FAMILY_PRIORS:   # most-specific first
        if n.startswith(prefix):
            return score
    return DEFAULT_CAPABILITY


# --- role gating -----------------------------------------------------------------------

# quality concentrates here → always the strongest model
HIGH_LEVERAGE_ROLES = frozenset({"moa_aggregator", "judge", "synthesizer"})
# need a specific capability (vision) or are deliberately cheap (router) → never gated
UNGATED_ROLES = frozenset({"vision", "router"})


def strongest(pool: List["ModelSlot"]) -> "ModelSlot":
    return max(pool, key=lambda s: capability_of(s.model))


def _reslot(src: "ModelSlot", role: str, temperature: float) -> "ModelSlot":
    return src.model_copy(update={"name": role, "temperature": temperature})


def gate_role(
    role: str,
    resolved: "ModelSlot",
    pool: List["ModelSlot"],
    floor: float,
    min_aggregator: float,
) -> "ModelSlot":
    """Return the model that *should* serve `role` under the capability policy.

    Never returns None / never empties a role: if nothing clears the floor it falls back to
    the strongest available model.
    """
    if role in UNGATED_ROLES or not pool:
        return resolved
    top = strongest(pool)
    if role in HIGH_LEVERAGE_ROLES:
        # the aggregator/verifier/synthesizer must be the strongest we have
        if resolved.model == top.model:
            return resolved
        return _reslot(top, role, resolved.temperature)
    # proposer / parser: a below-floor model loses its vote
    if capability_of(resolved.model) >= floor:
        return resolved
    passing = [s for s in pool if capability_of(s.model) >= floor]
    replacement = max(passing, key=lambda s: capability_of(s.model)) if passing else top
    return _reslot(replacement, role, resolved.temperature)


def excluded_from_council(pool: List["ModelSlot"], floor: float) -> List[str]:
    """Models present in the pool but below the floor — reported for observability."""
    return sorted({s.model for s in pool if capability_of(s.model) < floor})


# --- calibration (real; no stub) -------------------------------------------------------

# small, fully checkable set — a mix of a trap, multi-step, and hard items
CALIBRATION_SET = [
    ("A bat and a ball cost $1.10 total. The bat costs $1.00 more than the ball. How many cents is the ball?", 5),
    ("How many months of the year have exactly 28 days?", 12),
    ("A store had 120 apples; it sold 3/8 in the morning and 40 more later. How many are left?", 35),
    ("What are the last two digits of 7^2023? Give a two-digit integer.", 43),
    ("In how many ways can you make change for one dollar with pennies, nickels, dimes, quarters?", 242),
    ("How many trailing zeros does 100! have?", 24),
    ("At exactly 3:00 what is the angle in degrees between a clock's hands?", 90),
    ("If you overtake the person in 2nd place in a race, what place are you in? Give the number.", 2),
]
_COT = "\n\nSolve step by step, then end with a line exactly like: Answer: <final integer>"


def _grade(resp: str, num: int) -> bool:
    import re
    if not resp:
        return False
    low = resp.lower()
    m = re.search(r"answer:\s*(.+)", low)
    tail = (m.group(1) if m else low)[:120]
    nums = re.findall(r"-?\d+", tail) or re.findall(r"-?\d+", low)
    return bool(nums) and int(nums[-1]) == num


async def calibrate_model(slot: "ModelSlot", config) -> float:
    """Measure a model's capability (0..100) on the calibration set via the provider layer."""
    from metis.models.provider import create_provider

    provider = create_provider(slot, config)
    correct = 0
    try:
        for q, num in CALIBRATION_SET:
            try:
                ans = await provider.complete_text("You are a careful solver.", q + _COT, temperature=0.0)
                if _grade(ans, num):
                    correct += 1
            except Exception:
                pass
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    return round(100.0 * correct / len(CALIBRATION_SET), 1)


async def calibrate_pool(pool: List["ModelSlot"], config) -> Dict[str, float]:
    """Calibrate every distinct model in the pool. Returns {model: score}."""
    scores: Dict[str, float] = {}
    for slot in pool:
        if slot.model in scores:
            continue
        scores[slot.model] = await calibrate_model(slot, config)
    return scores
