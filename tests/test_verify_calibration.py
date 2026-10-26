"""verify_score calibration metrics (metis/verify/calibration.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis.verify.calibration import (
    calibration_report,
    format_report,
    jury_outcome,
    p_correct,
    verdicts_from_jury_bench,
)

RESULTS = Path(__file__).resolve().parents[1] / "bench" / "results"


def test_a_score_belongs_to_the_side_that_won():
    assert p_correct("pass", 0.9) == 0.9
    assert p_correct("fail", 0.9) == pytest.approx(0.1)
    assert p_correct("split", 0.0) == 0.5


def test_a_perfectly_calibrated_set_has_zero_ece():
    verdicts = [("pass", 0.9, True)] * 9 + [("pass", 0.9, False)]
    report = calibration_report(verdicts, bins=10)
    assert report.ece == pytest.approx(0.0)
    assert report.brier == pytest.approx(0.09)
    assert report.paid == 10 and report.paid_wrong == 1


def test_an_overconfident_set_shows_its_gap():
    verdicts = [("pass", 0.95, True)] * 7 + [("pass", 0.95, False)] * 3
    report = calibration_report(verdicts, bins=5)
    top = report.bins[-1]
    assert top.n == 10 and top.mean_p == pytest.approx(0.95) and top.accuracy == pytest.approx(0.7)
    assert report.ece == pytest.approx(0.25)
    assert report.max_gap == pytest.approx(0.25)


def test_score_one_lands_in_the_last_bin_and_below_the_bar_is_not_paid():
    report = calibration_report([("pass", 1.0, True), ("pass", 0.69, True), ("fail", 1.0, False)], bar=0.7)
    assert report.bins[-1].n == 1
    assert report.bins[0].n == 1
    assert report.paid == 1 and report.right_not_paid == 1


def test_empty_input_is_an_error():
    with pytest.raises(ValueError):
        calibration_report([])


def test_jury_outcome_matches_the_jury_rule():
    seat = lambda f, s: {"fulfils": f, "score": s}  # noqa: E731
    assert jury_outcome([seat(True, 1.0)] * 4 + [{"fulfils": None}]) == ("pass", 0.8)
    assert jury_outcome([seat(False, 0.0)] * 3 + [seat(True, 1.0)] * 2) == ("fail", 0.6)
    assert jury_outcome([seat(True, 1.0)] * 2 + [seat(False, 0.0)] * 2 + [{"fulfils": None}])[0] == "split"


def test_the_recorded_jury_runs_are_measured():
    files = sorted(RESULTS.glob("*.json"))
    assert files, "bench/results ships the 2026-10-03 jury runs"
    pooled = []
    for f in files:
        pooled.extend(verdicts_from_jury_bench(json.loads(f.read_text())))
    report = calibration_report(pooled, bins=5)
    assert report.n == 24 * len(files)
    # what docs/benchmarks/VERIFY-CALIBRATION-2026-10-23.md reports
    assert report.paid == 57 and report.paid_wrong == 1
    assert report.brier == pytest.approx(0.047, abs=0.001)
    assert report.ece == pytest.approx(0.085, abs=0.001)
    assert "Brier=" in format_report(report)
