#!/usr/bin/env python3
"""Frontier bake-off: DeepSeek-V4-Pro × MiniMax-M3 × Kimi-K3 (direct calls).

Real HTTP — no mocks. Grades the shared capability calibration set (traps +
multi-step integers). Writes JSON + a short Markdown summary under docs/benchmarks/.

Usage (on a host with keys, or with env exported):

  export DEEPSEEK_API_KEY=...
  export OPENROUTER_API_KEY=...
  python3 metis/scripts/bench_frontier_bakeoff.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "benchmarks"
COT = "\n\nSolve step by step, then end with a line exactly like: Answer: <final integer>"

# Same set as metis.agents.capability.CALIBRATION_SET — keep in sync.
CASES: list[tuple[str, int, str]] = [
    ("A bat and a ball cost $1.10 total. The bat costs $1.00 more than the ball. How many cents is the ball?", 5, "trap"),
    ("How many months of the year have exactly 28 days?", 12, "trap"),
    ("A store had 120 apples; it sold 3/8 in the morning and 40 more later. How many are left?", 35, "math"),
    ("What are the last two digits of 7^2023? Give a two-digit integer.", 43, "math"),
    ("In how many ways can you make change for one dollar with pennies, nickels, dimes, quarters?", 242, "math"),
    ("How many trailing zeros does 100! have?", 24, "math"),
    ("At exactly 3:00 what is the angle in degrees between a clock's hands?", 90, "logic"),
    ("If you overtake the person in 2nd place in a race, what place are you in? Give the number.", 2, "trap"),
]

MODELS: list[dict[str, str]] = [
    {
        "name": "DeepSeek-V4-Pro",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "env": "DEEPSEEK_API_KEY",
    },
    {
        "name": "DeepSeek-V4-Flash",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "env": "DEEPSEEK_API_KEY",
    },
    {
        "name": "MiniMax-M3",
        "model": "minimax/minimax-m3",
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
    },
    {
        "name": "Kimi-K3",
        "model": "moonshotai/kimi-k3",
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
    },
    {
        "name": "Kimi-K2.6",
        "model": "moonshotai/kimi-k2.6",
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
    },
]


@dataclass
class CaseResult:
    q: str
    expected: int
    category: str
    ok: bool
    latency_s: float
    answer_tail: str
    error: str = ""


def _grade(resp: str, num: int) -> bool:
    if not resp:
        return False
    low = resp.lower()
    m = re.search(r"answer:\s*(.+)", low)
    tail = (m.group(1) if m else low)[:120]
    nums = re.findall(r"-?\d+", tail) or re.findall(r"-?\d+", low)
    return bool(nums) and int(nums[-1]) == num


def _chat(base_url: str, api_key: str, model: str, prompt: str, timeout: float = 90.0) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a careful solver."},
                {"role": "user", "content": prompt + COT},
            ],
            "temperature": 0.0,
            "max_tokens": 1200,
        }
    ).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://metis.modelmarket.dev",
            "X-Title": "Metis-bakeoff",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    # reasoning models: prefer content; fall back to reasoning_content if empty
    content = (msg.get("content") or "").strip()
    if not content:
        content = (msg.get("reasoning_content") or "").strip()
    return content


def run_model(spec: dict[str, str]) -> dict[str, Any]:
    key = os.environ.get(spec["env"], "").strip()
    if not key:
        return {"name": spec["name"], "skipped": True, "reason": f"missing {spec['env']}"}
    results: list[CaseResult] = []
    for q, expected, cat in CASES:
        t0 = time.perf_counter()
        err = ""
        text = ""
        try:
            text = _chat(spec["base_url"], key, spec["model"], q)
            ok = _grade(text, expected)
        except Exception as exc:  # noqa: BLE001 — collect per-case
            ok = False
            err = f"{type(exc).__name__}: {exc}"
        lat = time.perf_counter() - t0
        results.append(
            CaseResult(
                q=q[:80],
                expected=expected,
                category=cat,
                ok=ok,
                latency_s=round(lat, 2),
                answer_tail=(text or "")[-160:].replace("\n", " "),
                error=err,
            )
        )
        print(f"  [{spec['name']}] {cat:5} {'✓' if ok else '✗'} {lat:5.1f}s  {q[:48]}…", flush=True)
    correct = sum(1 for r in results if r.ok)
    by_cat: dict[str, list[int]] = {}
    for r in results:
        hit, tot = by_cat.setdefault(r.category, [0, 0])
        by_cat[r.category] = [hit + (1 if r.ok else 0), tot + 1]
    lats = [r.latency_s for r in results]
    return {
        "name": spec["name"],
        "model": spec["model"],
        "skipped": False,
        "correct": correct,
        "total": len(results),
        "accuracy": round(100.0 * correct / len(results), 1),
        "median_latency_s": round(sorted(lats)[len(lats) // 2], 2) if lats else 0,
        "by_cat": by_cat,
        "cases": [asdict(r) for r in results],
    }


def write_report(payload: dict[str, Any]) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    day = date.today().isoformat()
    json_path = OUT_DIR / f"bench-frontier-{day}.json"
    md_path = OUT_DIR / f"HEAD-TO-HEAD-{day}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    rows = [s for s in payload["systems"] if not s.get("skipped")]
    rows.sort(key=lambda s: (-s["accuracy"], s["median_latency_s"]))
    lines = [
        f"# Metis frontier bake-off — {day}",
        "",
        "> Real HTTP, no mocks. Calibration set (8 checkable items: traps + multi-step).",
        f"> Raw: [`bench-frontier-{day}.json`](bench-frontier-{day}.json).",
        "",
        "## Result",
        "",
        "| System | Acc | trap | math | logic | Median latency |",
        "|--------|:---:|:---:|:---:|:---:|---:|",
    ]
    for s in rows:
        bc = s["by_cat"]
        def fmt(cat: str) -> str:
            h, t = bc.get(cat, [0, 0])
            return f"{h}/{t}"
        lines.append(
            f"| {s['name']} | **{s['accuracy']}%** ({s['correct']}/{s['total']}) | "
            f"{fmt('trap')} | {fmt('math')} | {fmt('logic')} | {s['median_latency_s']} s |"
        )
    lines += [
        "",
        "## Architecture recommendation",
        "",
        "1. **Base / aggregator / synthesizer / red-team = `deepseek-v4-pro`** — highest prior +",
        "   Self-MoA saturates checkable tasks (see 2026-07-11 bake-off C0).",
        "2. **Trap-diversity seat = `minimax/minimax-m3`** (OpenRouter) on `intent_parser_b` +",
        "   `moa_proposer_skeptic` — MiniMax was the only raw model that aced every System-1",
        "   trap in the July head-to-head; keep it as the dissenting voice.",
        "3. **Optional third diversifier = `moonshotai/kimi-k3`** for open-ended / ambiguous",
        "   work — not required when the set is checkable and V4-Pro + MiniMax already cover",
        "   the trap tail.",
        "4. **Cheap seats = `deepseek-v4-flash`** (judge, ambiguity, pragmatist, most parsers).",
        "5. **Never put a weak model in aggregator/verifier** — measured: weak aggregator",
        "   dragged a council *below* its best member (60% vs 90%).",
        "",
        "This matches live `prod.yaml` on metis.modelmarket.dev (V4-Pro Self-MoA + MiniMax",
        "skeptic). Do **not** use the legacy `deepseek-chat` alias in new benchmarks.",
        "",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    systems = []
    for spec in MODELS:
        print(f"=== {spec['name']} ({spec['model']}) ===", flush=True)
        systems.append(run_model(spec))
    payload = {
        "date": date.today().isoformat(),
        "n": len(CASES),
        "systems": systems,
    }
    jp, mp = write_report(payload)
    print(f"\nWrote {jp}\nWrote {mp}")
    for s in systems:
        if s.get("skipped"):
            print(f"  SKIP {s['name']}: {s.get('reason')}")
        else:
            print(f"  {s['name']}: {s['accuracy']}%  median {s['median_latency_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
