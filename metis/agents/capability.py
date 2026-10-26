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

One number per model hides that a model strong at arithmetic can be weaker at reading code or
at facts. `metis calibrate` therefore measures each task kind on its own set (reasoning,
coding, factual — the router's task_type names), and the gate ranks by the score for the
kind of the query being answered when this deployment has measured it.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from enum import Enum
from typing import Dict, List, Optional, Sequence, TYPE_CHECKING

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
    "kimi-k3": 93.0, "kimi-k2.7-code": 91.0,
    "kimi-k2.6": 90.0, "kimi-k2-thinking": 91.0, "kimi-k2.5": 88.0,
    "minimax-m3": 92.0, "minimax-m2.7": 88.0, "minimax-m2": 78.0,
    "glm-5.2": 88.0, "glm-5": 86.0, "glm-4.6": 82.0,
    # measured 2026-09-26 with `calibrate_model` (the 8-question set below, 7/8 = 87.5) through
    # OpenRouter from the appeal court's host — the jurors of Metis #2 and Metis #1's GLM seat.
    # Eight questions separate "strong" from "weak", not one strong model from another.
    "qwen3.8-max-prime": 87.5, "glm-5.3": 87.5,
    "mimo-v2.6-pro": 87.5, "seed-2-1-turbo": 75.0, "longcat-2.0": 100.0,
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


# Task kinds measured separately. The names are the router's task_type values
# (metis/router/classifier.py); research and planning have no set and rank by the overall score.
TASK_KINDS = ("reasoning", "coding", "factual")

# capability overrides loaded from `metis calibrate` (data/capability.json), keyed normalized
_CALIBRATED: Dict[str, float] = {}
# per task kind, from the same file: normalized model -> {task kind: score}
_CALIBRATED_BY_TASK: Dict[str, Dict[str, float]] = {}

# the task kind of the query being answered, set by the exoskeleton after routing
_TASK_KIND: ContextVar[Optional[str]] = ContextVar("metis_task_kind", default=None)


def set_task_kind(task: Optional[str]) -> Token:
    """Rank models for `task` in this context (None: by the overall score)."""
    return _TASK_KIND.set(task if task in TASK_KINDS else None)


def reset_task_kind(token: Token) -> None:
    _TASK_KIND.reset(token)


def current_task_kind() -> Optional[str]:
    return _TASK_KIND.get()


def _number(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def load_calibration(scores: Dict[str, object]) -> None:
    """Merge measured capability scores (from calibration) over the static priors.

    Reads both file shapes: the flat one older `metis calibrate` runs wrote
    ({model: score}) and the per-task one ({model: {"overall": s, "reasoning": s,
    "coding": s, "factual": s}}). A per-task entry without "overall" gets the mean of its
    task scores.
    """
    for model, value in scores.items():
        n = _normalize(model)
        if isinstance(value, dict):
            per = {t: _number(value.get(t)) for t in TASK_KINDS}
            per = {t: v for t, v in per.items() if v is not None}
            if per:
                _CALIBRATED_BY_TASK[n] = {**_CALIBRATED_BY_TASK.get(n, {}), **per}
            overall = _number(value.get("overall"))
            if overall is None and per:
                overall = sum(per.values()) / len(per)
            if overall is not None:
                _CALIBRATED[n] = overall
        elif _number(value) is not None:
            _CALIBRATED[n] = float(value)


# Family priors — version-drift fallback so a NEW release in a known frontier family
# (e.g. gpt-5.7, gemini-4-pro, claude-opus-4.9) gets a sensible frontier score instead of
# "unknown → mid", even before it's added above or calibrated. Most-specific prefix first.
FAMILY_PRIORS: List[tuple] = [
    ("gpt-5", 94.0), ("gpt-", 82.0), ("o4", 92.0), ("o3", 88.0),
    ("gemini-3", 90.0), ("gemini-2.5", 84.0), ("gemini-", 80.0),
    ("claude-opus", 94.0), ("claude-sonnet", 86.0), ("claude-haiku", 76.0), ("claude-", 85.0),
    ("grok-4", 88.0), ("grok-", 80.0),
    ("deepseek-v4", 90.0), ("deepseek-", 78.0),
    ("qwen3-max", 92.0), ("qwen3", 85.0), ("kimi-k3", 93.0), ("kimi-k2", 88.0), ("kimi", 84.0),
    ("glm-5", 85.0), ("glm-4", 80.0), ("minimax-m3", 92.0), ("minimax-m", 82.0),
    ("mimo-", 85.0), ("seed-", 75.0), ("longcat-", 85.0),
    ("llama-3.1-8b", 55.0), ("llama-3.2", 42.0), ("llama-4", 78.0), ("llama-", 62.0),
]


def capability_of(model: str, task: Optional[str] = None) -> float:
    """Relative capability (0..100).
    Calibrated score for `task` > calibrated score > exact prior > longest-prefix prior >
    frontier-family prior > default. A task score is used only when it was measured for this
    exact model; the priors are not split by task.
    """
    n = _normalize(model)
    if task:
        measured = _CALIBRATED_BY_TASK.get(n, {}).get(task)
        if measured is not None:
            return measured
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


def strongest(pool: List["ModelSlot"], task: Optional[str] = None) -> "ModelSlot":
    return max(pool, key=lambda s: capability_of(s.model, task))


def _reslot(src: "ModelSlot", role: str, temperature: float) -> "ModelSlot":
    return src.model_copy(update={"name": role, "temperature": temperature})


def _vendor_candidates(
    pool: List["ModelSlot"], avoid_vendors: Sequence[str],
) -> tuple[List["ModelSlot"], frozenset]:
    """The pool minus the vendors to avoid, relaxing the avoid list from its tail.

    `avoid_vendors` is in priority order. With a two-vendor pool it is impossible to
    avoid both writers of an answer, so the least important exclusion is dropped first
    rather than giving up on distinctness altogether. Returns (candidates, what was
    actually avoided); with nothing avoidable the whole pool comes back.
    """
    from metis.agents.diversity import vendor_of

    wanted = [v for v in avoid_vendors if v]
    for keep in range(len(wanted), 0, -1):
        avoided = frozenset(wanted[:keep])
        left = [s for s in pool if vendor_of(s.model) not in avoided]
        if left:
            return left, avoided
    return list(pool), frozenset()


def gate_role(
    role: str,
    resolved: "ModelSlot",
    pool: List["ModelSlot"],
    floor: float,
    min_aggregator: float,
    *,
    explicit: bool = False,
    avoid_vendors: Sequence[str] = (),
    task: Optional[str] = None,
) -> "ModelSlot":
    """Return the model that *should* serve `role` under the capability policy.

    Never returns None / never empties a role: if nothing clears the floor it falls back to
    the strongest available model.

    Two refinements for the high-leverage seats, both because the gate used to override
    the operator silently — a live `judge: minimax-m3` was served by kimi-k3, the same
    model the gate had also put in the aggregator seat:

      * `explicit` — the operator named this seat's model in `modules`. That choice is
        honoured when the model clears `min_aggregator`; the gate exists to stop a weak
        model landing in a high-leverage seat by accident, not to overrule a deliberate one.
      * `avoid_vendors` — vendors this seat must not share (the judge must not come from
        the lab that wrote the answer it audits). Relaxed from the tail when the pool is
        too small to honour all of it; see `_vendor_candidates`.
      * `task` — rank by the score measured for this kind of query (default: the kind the
        exoskeleton set for the current run; None ranks by the overall score).
    """
    if role in UNGATED_ROLES or not pool:
        return resolved
    if task is None:
        task = current_task_kind()

    def score(model: str) -> float:
        return capability_of(model, task)

    top = strongest(pool, task)
    if role in HIGH_LEVERAGE_ROLES:
        from metis.agents.diversity import vendor_of

        candidates, avoided = _vendor_candidates(pool, avoid_vendors)
        if explicit and score(resolved.model) >= min_aggregator \
                and vendor_of(resolved.model) not in avoided:
            return resolved
        # the aggregator/verifier/synthesizer must be the strongest we have
        best = strongest(candidates, task)
        if resolved.model == best.model:
            return resolved
        return _reslot(best, role, resolved.temperature)
    # proposer / parser: a below-floor model loses its vote
    if score(resolved.model) >= floor:
        return resolved
    passing = [s for s in pool if score(s.model) >= floor]
    replacement = max(passing, key=lambda s: score(s.model)) if passing else top
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

# reading code: what does the program print (each answer checked by running it)
CODING_SET = [
    ("x = [1, 2, 3]\ny = x\ny.append(4)\nprint(len(x))", 4),
    ("print(sum(i * i for i in range(5)))", 30),
    ("def f(n):\n    return n if n < 2 else f(n - 1) + f(n - 2)\nprint(f(10))", 55),
    ("print(len({c for c in 'mississippi'}))", 4),
    ("print(7 // -2)", -4),
    ("s = 'abcdef'\nprint(len(s[1:-1:2]))", 2),
    ("print(int('101', 2) + int('17', 8))", 20),
    ("d = {}\nfor w in 'a b a c b a'.split():\n    d[w] = d.get(w, 0) + 1\n"
     "print(d['a'] * 100 + d['b'] * 10 + d['c'])", 321),
]
_CODE_PROMPT = "What does this Python 3 program print?\n\n```python\n{}\n```"

# stable facts with integer answers
FACTUAL_SET = [
    ("In what year did the Apollo 11 crew first land on the Moon?", 1969),
    ("How many bones are in the typical adult human skeleton?", 206),
    ("What is the atomic number of gold?", 79),
    ("In what year did the Berlin Wall fall?", 1989),
    ("What is the boiling point of water at sea level in degrees Fahrenheit?", 212),
    ("How many chromosomes does a typical human body cell have?", 46),
    ("How many players does one team have on the pitch in association football?", 11),
    ("In what year was the first iPhone released?", 2007),
]

CALIBRATION_SETS = {
    "reasoning": CALIBRATION_SET,
    "coding": [(_CODE_PROMPT.format(code), num) for code, num in CODING_SET],
    "factual": FACTUAL_SET,
}


def _grade(resp: str, num: int) -> bool:
    import re
    if not resp:
        return False
    low = resp.lower()
    m = re.search(r"answer:\s*(.+)", low)
    tail = (m.group(1) if m else low)[:120]
    nums = re.findall(r"-?\d+", tail) or re.findall(r"-?\d+", low)
    return bool(nums) and int(nums[-1]) == num


async def calibrate_model_by_task(
    slot: "ModelSlot", config, tasks: Sequence[str] = TASK_KINDS,
) -> Dict[str, float]:
    """Measure a model (0..100) on each task kind's set via the provider layer.

    Returns {task: score, ..., "overall": score over every question asked}.
    """
    from metis.models.provider import create_provider

    provider = create_provider(slot, config)
    out: Dict[str, float] = {}
    correct_all = asked_all = 0
    try:
        for task in tasks:
            items = CALIBRATION_SETS[task]
            correct = 0
            for q, num in items:
                try:
                    ans = await provider.complete_text("You are a careful solver.", q + _COT, temperature=0.0)
                    if _grade(ans, num):
                        correct += 1
                except Exception:
                    pass
            out[task] = round(100.0 * correct / len(items), 1)
            correct_all += correct
            asked_all += len(items)
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    out["overall"] = round(100.0 * correct_all / asked_all, 1) if asked_all else 0.0
    return out


async def calibrate_model(slot: "ModelSlot", config) -> float:
    """Measure a model's capability (0..100) on the reasoning set via the provider layer."""
    return (await calibrate_model_by_task(slot, config, ("reasoning",)))["reasoning"]


async def calibrate_pool(
    pool: List["ModelSlot"], config, tasks: Sequence[str] = TASK_KINDS,
) -> Dict[str, Dict[str, float]]:
    """Calibrate every distinct model in the pool. Returns {model: {task: score, "overall": score}}."""
    scores: Dict[str, Dict[str, float]] = {}
    for slot in pool:
        if slot.model in scores:
            continue
        scores[slot.model] = await calibrate_model_by_task(slot, config, tasks)
    return scores
