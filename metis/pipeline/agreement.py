"""Agreement scoring between parallel parser and proposer outputs."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Set


def _normalize_goal(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _goal_similarity(goals: List[str]) -> float:
    normalized = [_normalize_goal(g) for g in goals if g]
    if len(normalized) < 2:
        return 1.0 if normalized else 0.0
    scores: List[float] = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            scores.append(SequenceMatcher(None, normalized[i], normalized[j]).ratio())
    return sum(scores) / len(scores)


def _jaccard(sets: List[Set[str]]) -> float:
    if len(sets) < 2:
        return 1.0
    scores: List[float] = []
    items = list(sets)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            union = a | b
            scores.append(1.0 if not union else len(a & b) / len(union))
    return sum(scores) / len(scores)


def _constraint_sets(outputs: List[Dict[str, Any]]) -> List[Set[str]]:
    result: List[Set[str]] = []
    for out in outputs:
        raw = out.get("constraints", [])
        if isinstance(raw, str):
            raw = [raw]
        result.append({_normalize_goal(str(c)) for c in raw if c})
    return result


def _ambiguity_penalty(outputs: List[Dict[str, Any]]) -> float:
    counts: List[int] = []
    for out in outputs:
        amb = out.get("ambiguities", out.get("ambiguity", []))
        if isinstance(amb, str):
            rank = {"low": 0, "medium": 1, "high": 2}
            counts.append(rank.get(amb.lower(), 1))
        elif isinstance(amb, list):
            counts.append(len(amb))
        else:
            counts.append(0)
    if len(counts) < 2:
        return 1.0
    spread = max(counts) - min(counts)
    return max(0.0, 1.0 - spread * 0.25)


def compute_agreement(parser_outputs: List[Dict[str, Any]]) -> float:
    """Weighted agreement score (0-1) across structured parser outputs."""
    if not parser_outputs:
        return 0.0
    if len(parser_outputs) == 1:
        return 1.0

    goals = [str(o.get("goal", o.get("summary", o.get("intent", "")))) for o in parser_outputs]
    goal_score = _goal_similarity(goals)
    constraint_score = _jaccard(_constraint_sets(parser_outputs))
    ambiguity_score = _ambiguity_penalty(parser_outputs)
    return round(0.5 * goal_score + 0.35 * constraint_score + 0.15 * ambiguity_score, 4)


def compute_proposer_agreement(proposals: List[str]) -> float:
    """Estimate agreement between MoA proposer text outputs (0-1)."""
    if not proposals:
        return 0.0
    if len(proposals) == 1:
        return 1.0
    scores: List[float] = []
    normed = [_normalize_goal(p) for p in proposals]
    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            scores.append(SequenceMatcher(None, normed[i], normed[j]).ratio())
    return round(sum(scores) / len(scores), 4)
