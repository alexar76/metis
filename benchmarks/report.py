"""Benchmark report generation — Markdown + JSON."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from benchmarks.harness import CaseResult, RunnerKind


@dataclass
class ModelSummary:
    model: str
    runner: RunnerKind
    cases: int = 0
    passed: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_calls: int = 0
    by_category: Dict[str, Dict[str, float]] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.cases) if self.cases else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.cases) if self.cases else 0.0

    @property
    def avg_cost_usd(self) -> float:
        return (self.total_cost_usd / self.cases) if self.cases else 0.0

    @property
    def avg_calls(self) -> float:
        return (self.total_calls / self.cases) if self.cases else 0.0


def summarize(results: List[CaseResult]) -> List[ModelSummary]:
    buckets: Dict[Tuple[str, RunnerKind], ModelSummary] = {}

    for r in results:
        key = (r.model, r.runner)
        if key not in buckets:
            buckets[key] = ModelSummary(model=r.model, runner=r.runner)
        s = buckets[key]
        s.cases += 1
        if r.passed:
            s.passed += 1
        s.total_latency_ms += r.latency_ms
        s.total_cost_usd += r.estimated_cost_usd
        s.total_calls += r.calls_count
        cat = s.by_category.setdefault(r.category, {"cases": 0, "passed": 0, "latency_ms": 0.0})
        cat["cases"] += 1
        if r.passed:
            cat["passed"] += 1
        cat["latency_ms"] += r.latency_ms

    return sorted(buckets.values(), key=lambda x: (x.model, x.runner.value))


def _category_pass_rate(cat: Dict[str, float]) -> float:
    cases = cat.get("cases", 0)
    return (cat.get("passed", 0) / cases) if cases else 0.0


def _highlights(summaries: List[ModelSummary]) -> Tuple[List[str], List[str]]:
    """Return (metis_wins, direct_wins) bullet lines — honest comparison."""
    metis_wins: List[str] = []
    direct_wins: List[str] = []

    by_model: Dict[str, Dict[RunnerKind, ModelSummary]] = defaultdict(dict)
    for s in summaries:
        by_model[s.model][s.runner] = s

    for model, runners in by_model.items():
        direct = runners.get(RunnerKind.DIRECT)
        metis = runners.get(RunnerKind.METIS)
        if not direct or not metis:
            continue

        trap_cats = {"trap", "ambiguous"}
        simple_cats = {"simple"}

        for cat in trap_cats:
            d_cat = direct.by_category.get(cat, {})
            m_cat = metis.by_category.get(cat, {})
            if d_cat and m_cat:
                d_rate = _category_pass_rate(d_cat)
                m_rate = _category_pass_rate(m_cat)
                if m_rate > d_rate:
                    metis_wins.append(
                        f"**{model}** — {cat}: Metis pass rate {m_rate:.0%} vs Direct {d_rate:.0%}"
                    )
                elif d_rate > m_rate:
                    direct_wins.append(
                        f"**{model}** — {cat}: Direct pass rate {d_rate:.0%} vs Metis {m_rate:.0%}"
                    )

        for cat in simple_cats:
            d_cat = direct.by_category.get(cat, {})
            m_cat = metis.by_category.get(cat, {})
            if d_cat and m_cat:
                d_lat = d_cat["latency_ms"] / max(d_cat["cases"], 1)
                m_lat = m_cat["latency_ms"] / max(m_cat["cases"], 1)
                if d_lat < m_lat * 0.8:
                    direct_wins.append(
                        f"**{model}** — simple latency: Direct {d_lat:.0f}ms vs Metis {m_lat:.0f}ms"
                    )
                elif m_lat < d_lat * 0.8:
                    metis_wins.append(
                        f"**{model}** — simple latency: Metis {m_lat:.0f}ms vs Direct {d_lat:.0f}ms"
                    )

        if metis.pass_rate > direct.pass_rate + 0.05:
            metis_wins.append(
                f"**{model}** — overall pass rate: Metis {metis.pass_rate:.0%} vs Direct {direct.pass_rate:.0%}"
            )
        elif direct.pass_rate > metis.pass_rate + 0.05:
            direct_wins.append(
                f"**{model}** — overall pass rate: Direct {direct.pass_rate:.0%} vs Metis {metis.pass_rate:.0%}"
            )

        if direct.avg_latency_ms < metis.avg_latency_ms * 0.7 and direct.pass_rate >= metis.pass_rate - 0.1:
            direct_wins.append(
                f"**{model}** — speed at similar quality: Direct {direct.avg_latency_ms:.0f}ms vs Metis {metis.avg_latency_ms:.0f}ms"
            )

    return metis_wins, direct_wins


def render_markdown(
    results: List[CaseResult],
    *,
    dataset: str,
    models: List[str],
    skipped: Optional[List[str]] = None,
) -> str:
    summaries = summarize(results)
    metis_wins, direct_wins = _highlights(summaries)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Metis Benchmark Report",
        "",
        f"Generated: {ts}",
        f"Dataset: `{dataset}`",
        f"Models: {', '.join(f'`{m}`' for m in models) if models else '_none_'}",
        "",
    ]

    if skipped:
        lines.extend([
            f"> Skipped (missing API keys): {', '.join(f'`{m}`' for m in skipped)}",
            "",
        ])

    lines.extend([
        "## Summary",
        "",
        "| Model | Runner | Cases | Pass rate | Avg latency (ms) | Avg cost (USD) | Avg calls |",
        "|-------|--------|------:|----------:|-----------------:|---------------:|----------:|",
    ])

    for s in summaries:
        lines.append(
            f"| {s.model} | {s.runner.value} | {s.cases} | {s.pass_rate:.0%} | "
            f"{s.avg_latency_ms:.0f} | {s.avg_cost_usd:.6f} | {s.avg_calls:.1f} |"
        )

    lines.extend(["", "## By category", ""])
    for s in summaries:
        lines.append(f"### {s.model} — {s.runner.value}")
        lines.append("")
        lines.append("| Category | Cases | Pass rate | Avg latency (ms) |")
        lines.append("|----------|------:|----------:|-----------------:|")
        for cat, stats in sorted(s.by_category.items()):
            rate = _category_pass_rate(stats)
            lat = stats["latency_ms"] / max(stats["cases"], 1)
            lines.append(f"| {cat} | {int(stats['cases'])} | {rate:.0%} | {lat:.0f} |")
        lines.append("")

    lines.extend(["## Where Metis wins", ""])
    if metis_wins:
        lines.extend(f"- {line}" for line in metis_wins)
    else:
        lines.append("_No clear Metis advantage in this run._")

    lines.extend(["", "## Where Direct wins", ""])
    if direct_wins:
        lines.extend(f"- {line}" for line in direct_wins)
    else:
        lines.append("_No clear Direct advantage in this run._")

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- **Trap / ambiguous**: Metis should ask for clarification via the confidence gate.",
        "- **Reasoning / code**: Metis council + verifier should improve pass rate at higher cost.",
        "- **Simple FAQ**: Direct should win on latency; multi-agent overhead is wasted.",
        "- **Factual**: Depends on tools; web search disabled in default benchmark config.",
        "",
    ])

    return "\n".join(lines)


def write_report(
    results: List[CaseResult],
    output: Path,
    *,
    dataset: str,
    models: List[str],
    skipped: Optional[List[str]] = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    md_path = output.with_suffix(".md") if output.suffix != ".md" else output
    json_path = md_path.with_suffix(".json")

    md_path.write_text(
        render_markdown(results, dataset=dataset, models=models, skipped=skipped),
        encoding="utf-8",
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "models": models,
        "skipped_models": skipped or [],
        "summaries": [
            {
                "model": s.model,
                "runner": s.runner.value,
                "cases": s.cases,
                "pass_rate": s.pass_rate,
                "avg_latency_ms": s.avg_latency_ms,
                "avg_cost_usd": s.avg_cost_usd,
                "avg_calls": s.avg_calls,
                "by_category": s.by_category,
            }
            for s in summarize(results)
        ],
        "results": [r.to_dict() for r in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path
