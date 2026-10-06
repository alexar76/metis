#!/usr/bin/env python3
"""Three seats or five? A measured comparison on checkable tasks.

    # 1. build the hub-identical audit prompts (needs aimarket-hub importable)
    python3 metis/bench/jury_3v5.py build --out /tmp/jury_cases.json
    # 2. run them through a live Metis jury (on the Metis host, inside the container: the key never moves)
    python3 jury_3v5.py run --cases /tmp/jury_cases.json --out /tmp/jury_votes.json --url http://127.0.0.1:8080
    # 3. tally any sub-roster from the same votes
    python3 metis/bench/jury_3v5.py tally --votes /tmp/jury_votes.json

Every case is run ONCE through the full roster; smaller juries are computed from the same
per-juror votes with the jury's own arithmetic (metis/verify/jury.py): a side wins only with a
strict majority of the whole roster, an abstention votes for nobody, and the score is
agreement × median confidence of the winning side, checked against the hub's 0.7 bar. So the
comparison isolates the roster — same prompts, same answers, same moment.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import statistics
import sys
import time
from pathlib import Path

CASES = [
    ("Return the prime factorization of 1000009: primes whose product is exactly 1000009.",
     {"factors": [293, 3413]}, {"factors": [7, 373, 383]}),
    ("Return the prime factorization of 600851475143: primes whose product is exactly 600851475143.",
     {"factors": [71, 839, 1471, 6857]}, {"factors": [71, 839, 1471, 6863]}),
    ("Sort [5, 3, 9, 1, 7] in ascending order.", {"sorted": [1, 3, 5, 7, 9]}, {"sorted": [1, 3, 7, 5, 9]}),
    ("Return the sum of [12, 7, 30, 1].", {"sum": 50}, {"sum": 51}),
    ("Convert 26.2 miles to kilometres (1 mile = 1.609344 km), to 4 decimals.", {"km": 42.1648}, {"km": 42.6}),
    # Reworded after the first runs: "how many days from A to B" is ambiguous (counting both ends
    # gives 73), and five jurors accepted 73 as the "wrong" answer.
    ("How many days after 2026-01-01 does 2026-03-14 fall? (2026-01-02 is 1 day after.)", {"days": 72}, {"days": 73}),
    ("Return a JSON object with the fields name, email and age for Ada Lovelace, born 1815 (age as of 1852).",
     {"name": "Ada Lovelace", "email": "ada@example.org", "age": 36}, {"name": "Ada Lovelace", "email": "ada@example.org"}),
    ("Count the vowels (a, e, i, o, u) in the word 'verification'.", {"vowels": 6}, {"vowels": 5}),
    ("Reverse the string 'escrow'.", {"reversed": "worcse"}, {"reversed": "worcsa"}),
    ("Is 97 a prime number? Answer true or false.", {"prime": True}, {"prime": False}),
    ("Translate the English word 'cat' into French.", {"french": "chat"}, {"french": "chien"}),
    ("What is the capital city of Australia?", {"capital": "Canberra"}, {"capital": "Sydney"}),
]

ROSTERS = {
    "3 seats — one lineage (DeepSeek, MiniMax, GLM)": ("deepseek", "minimax", "zhipu"),
    "3 seats — three lineages (DeepSeek, Claude, Mistral)": ("deepseek", "anthropic", "mistral"),
    "5 seats (all)": ("deepseek", "minimax", "zhipu", "anthropic", "mistral"),
}
BAR = 0.7


def build(out: str) -> None:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "aimarket-hub"))
    from aimarket_hub.verified_settlement import VerifiedSettlementService as S
    cases = []
    for i, (intent, honest, wrong) in enumerate(CASES):
        for truth, output in (("honest", honest), ("wrong", wrong)):
            aid = secrets.token_hex(16)
            cases.append({"case": i, "truth": truth, "intent": intent, "output": output, "payload": {
                "input": S._compose_input(intent, json.dumps(output), aid),
                "route": "jury", "min_verify_score": BAR, "audit_id": aid}})
    Path(out).write_text(json.dumps(cases, indent=1))
    print(f"{len(cases)} cases -> {out}")


def run(cases_path: str, out: str, url: str) -> None:
    import httpx
    key = os.environ["METIS_API_KEY"]
    cases = json.loads(Path(cases_path).read_text())
    for c in cases:
        t = time.time()
        r = httpx.post(f"{url}/v1/verify", json=c["payload"], timeout=600,
                       headers={"Authorization": f"Bearer {key}"})
        env = r.json()
        c["seconds"] = round(time.time() - t, 1)
        c["jury"] = env.get("jury") or []
        c["verify_score"] = env.get("verify_score")
        c.pop("payload")
        print(c["case"], c["truth"], c["seconds"], [(v["vendor"], v.get("fulfils")) for v in c["jury"]], flush=True)
        Path(out).write_text(json.dumps(cases, indent=1))


def decide(votes: list[dict]) -> tuple[str, float]:
    """The jury's own rule on a sub-roster: strict majority of the WHOLE roster, abstentions vote
    for nobody; score = agreement × median confidence of the winning side; decided only at the bar."""
    n = len(votes)
    yes = [v for v in votes if v.get("fulfils") is True]
    no = [v for v in votes if v.get("fulfils") is False]
    for side, label, conf in ((yes, "pass", lambda v: v["score"]), (no, "fail", lambda v: 1 - v["score"])):
        if len(side) * 2 > n:
            score = len(side) / n * statistics.median(conf(v) for v in side)
            return (label if score >= BAR else "undecided"), score
    return "undecided", 0.0


def tally(votes_path: str, exclude: tuple[int, ...] = ()) -> None:
    cases = [c for c in json.loads(Path(votes_path).read_text()) if c["case"] not in exclude]
    present = sorted({v["vendor"] for c in cases for v in c["jury"]})
    core = ("deepseek", "minimax", "zhipu", "anthropic")
    rosters = {"3 seats — one lineage (DeepSeek, MiniMax, GLM)": ("deepseek", "minimax", "zhipu")}
    for fifth in [v for v in present if v not in core] or ["mistral"]:
        rosters[f"3 seats — three lineages (DeepSeek, Claude, {fifth})"] = ("deepseek", "anthropic", fifth)
        rosters[f"5 seats (with {fifth})"] = core + (fifth,)
    if len(present) > 5:
        rosters[f"{len(present)} seats (all)"] = tuple(present)
    for name, vendors in rosters.items():
        right = wrong = undecided = 0
        latency = []
        for c in cases:
            seats = [v for v in c["jury"] if v["vendor"] in vendors]
            if len(seats) != len(vendors):
                continue
            outcome, _ = decide(seats)
            want = "pass" if c["truth"] == "honest" else "fail"
            right += outcome == want
            undecided += outcome == "undecided"
            wrong += outcome not in (want, "undecided")
            latency.append(max(v.get("latency_ms", 0) for v in seats) / 1000)
        total = right + wrong + undecided
        print(f"{name}: right {right}/{total}, undecided {undecided}, WRONG {wrong}, "
              f"median wait {statistics.median(latency):.1f}s, slowest {max(latency):.1f}s")
    abst = {}
    for c in cases:
        for v in c["jury"]:
            if v.get("fulfils") is None:
                abst[v["vendor"]] = abst.get(v["vendor"], 0) + 1
            elif (v["fulfils"] is True) != (c["truth"] == "honest"):
                abst[v["vendor"] + " (wrong vote)"] = abst.get(v["vendor"] + " (wrong vote)", 0) + 1
    print("per juror — abstentions / wrong votes:", abst or "none")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", required=True)
    r = sub.add_parser("run"); r.add_argument("--cases", required=True); r.add_argument("--out", required=True)
    r.add_argument("--url", default="http://127.0.0.1:8080")
    t = sub.add_parser("tally"); t.add_argument("--votes", required=True)
    t.add_argument("--exclude-case", type=int, action="append", default=[],
                   help="leave a task out (e.g. 5: the original, ambiguous 'days from A to B')")
    a = ap.parse_args()
    {"build": lambda: build(a.out), "run": lambda: run(a.cases, a.out, a.url), "tally": lambda: tally(a.votes, tuple(a.exclude_case))}[a.cmd]()
