"""Is verify_score a probability? Calibration metrics over labelled verdicts.

The hub pays when a verdict passes with verify_score >= 0.7, which reads the score as "the
answer is right with at least this probability". That holds only if the score is calibrated:
of the answers passed at 0.95, about 95% should be right. This module measures it on cases
whose truth is known (bench/results/*.json from bench/jury_3v5.py, or any list of
(verdict, score, correct) triples):

  * Brier score — mean squared gap between the stated probability and the outcome (0 best);
  * expected calibration error (ECE) — per score bin, |mean stated probability - share right|,
    weighted by the bin's size; the maximum gap is reported too;
  * the reliability table itself (one row per bin);
  * at the bar: how many answers would have been paid, and how many of those were wrong.

A score belongs to the side that won: a "fail" at 0.9 says the answer is wrong with 0.9, so
the probability that the answer is right is 1 - 0.9. A split or unavailable jury states nothing
and counts as 0.5.

Small samples say little: with 24 cases a bin holds a handful, and the report prints counts so
nobody reads a 100% from three cases as a property of the jury.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def p_correct(outcome: str, verify_score: float) -> float:
    """Probability the judged answer is right, as the verdict states it."""
    if outcome == "pass":
        return float(verify_score)
    if outcome == "fail":
        return 1.0 - float(verify_score)
    return 0.5


@dataclass
class Bin:
    lo: float
    hi: float
    n: int = 0
    mean_p: float = 0.0
    accuracy: float = 0.0

    @property
    def gap(self) -> float:
        return abs(self.mean_p - self.accuracy) if self.n else 0.0


@dataclass
class CalibrationReport:
    n: int
    brier: float
    ece: float
    max_gap: float
    bins: List[Bin] = field(default_factory=list)
    bar: float = 0.7
    paid: int = 0
    paid_wrong: int = 0
    right_not_paid: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n": self.n,
            "brier": round(self.brier, 4),
            "ece": round(self.ece, 4),
            "max_gap": round(self.max_gap, 4),
            "bar": self.bar,
            "paid": self.paid,
            "paid_wrong": self.paid_wrong,
            "right_not_paid": self.right_not_paid,
            "bins": [
                {"lo": b.lo, "hi": b.hi, "n": b.n,
                 "mean_p": round(b.mean_p, 4), "accuracy": round(b.accuracy, 4)}
                for b in self.bins
            ],
        }


def calibration_report(
    verdicts: Iterable[Tuple[str, float, bool]], *, bins: int = 5, bar: float = 0.7,
) -> CalibrationReport:
    """Calibration of (outcome, verify_score, answer_is_right) triples.

    Bins split [0, 1] evenly; the last one includes 1.0. "Paid" means what the hub pays on:
    outcome "pass" with verify_score >= bar.
    """
    rows = [(outcome, float(score), bool(right)) for outcome, score, right in verdicts]
    if not rows:
        raise ValueError("no verdicts to measure")
    if bins < 1:
        raise ValueError("bins must be >= 1")
    probs = [(p_correct(o, s), right) for o, s, right in rows]
    brier = statistics.fmean((p - (1.0 if right else 0.0)) ** 2 for p, right in probs)

    edges = [i / bins for i in range(bins + 1)]
    table: List[Bin] = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        inside = [(p, r) for p, r in probs if lo <= p < hi or (i == bins - 1 and p == hi)]
        b = Bin(lo=round(lo, 4), hi=round(hi, 4), n=len(inside))
        if inside:
            b.mean_p = statistics.fmean(p for p, _ in inside)
            b.accuracy = sum(1 for _, r in inside if r) / len(inside)
        table.append(b)
    n = len(probs)
    ece = sum(b.n / n * b.gap for b in table)
    max_gap = max((b.gap for b in table if b.n), default=0.0)

    paid = [(o, s, r) for o, s, r in rows if o == "pass" and s >= bar]
    return CalibrationReport(
        n=n, brier=brier, ece=ece, max_gap=max_gap, bins=table, bar=bar,
        paid=len(paid),
        paid_wrong=sum(1 for _, _, r in paid if not r),
        right_not_paid=sum(1 for o, s, r in rows if r and not (o == "pass" and s >= bar)),
    )


def jury_outcome(votes: Sequence[Dict[str, Any]], roster_size: Optional[int] = None) -> Tuple[str, float]:
    """The jury's own rule (metis/verify/jury.py `tally`) over recorded votes.

    A side wins with more than half of the WHOLE roster; abstentions vote for nobody; the score
    is agreement x median confidence of the winning side.
    """
    size = max(int(roster_size or 0), len(votes), 1)
    ayes = [v for v in votes if v.get("fulfils") is True]
    nays = [v for v in votes if v.get("fulfils") is False]
    if len(ayes) * 2 > size:
        side, outcome = ayes, "pass"
    elif len(nays) * 2 > size:
        side, outcome = nays, "fail"
    else:
        return "split", 0.0
    conf = statistics.median(
        float(v["score"]) if outcome == "pass" else 1.0 - float(v["score"]) for v in side
    )
    return outcome, round(len(side) / size * conf, 4)


def verdicts_from_jury_bench(cases: Iterable[Dict[str, Any]]) -> List[Tuple[str, float, bool]]:
    """(outcome, verify_score, right) from bench/jury_3v5.py results.

    A case is right when the output shown to the jury was the honest one; the outcome comes
    from the recorded votes, the score is the one the live jury returned when present.
    """
    out: List[Tuple[str, float, bool]] = []
    for case in cases:
        votes = case.get("jury") or []
        if not votes:
            continue
        outcome, score = jury_outcome(votes)
        live = case.get("verify_score")
        if isinstance(live, (int, float)) and not isinstance(live, bool) and outcome != "split":
            score = float(live)
        out.append((outcome, score, case.get("truth") == "honest"))
    return out


def format_report(report: CalibrationReport, title: str = "") -> str:
    lines = []
    if title:
        lines.append(title)
    lines.append(
        f"n={report.n}  Brier={report.brier:.3f}  ECE={report.ece:.3f}  max gap={report.max_gap:.3f}  "
        f"paid at >= {report.bar}: {report.paid} (wrong {report.paid_wrong}), "
        f"right but not paid: {report.right_not_paid}"
    )
    lines.append(f"  {'P(right) bin':<14} {'n':>4} {'stated':>8} {'actual':>8}")
    for b in report.bins:
        if not b.n:
            continue
        lines.append(f"  [{b.lo:.1f}, {b.hi:.1f}{']' if b.hi == 1.0 else ')':<5} {b.n:>4} "
                     f"{b.mean_p:>8.3f} {b.accuracy:>8.3f}")
    return "\n".join(lines)
