"""Benchmark harness tests — mock provider only (CI-safe)."""

from __future__ import annotations

import pytest

from benchmarks.harness import (
    BenchmarkCase,
    BenchmarkRunner,
    DirectProvider,
    MetisPipeline,
    RunnerKind,
    evaluate_checks,
    load_dataset,
)
from benchmarks.providers import ModelSpec
from metis.config import ProviderKind
from metis.exoskeleton import RunStatus


MOCK_SPEC = ModelSpec(
    name="mock",
    model="mock-model",
    provider=ProviderKind.MOCK,
    base_url="mock://local",
    api_key="mock",
    provider_label="mock",
)


@pytest.mark.benchmark
def test_load_all_datasets():
    cases = load_dataset("all")
    assert len(cases) >= 40
    ids = {c.id for c in cases}
    assert "trap-01" in ids
    assert "math-06" in ids
    assert "simple-01" in ids


@pytest.mark.benchmark
def test_evaluate_checks_answer_contains():
    case = BenchmarkCase(id="t", query="q", category="simple", expected_checks={"answer_contains": "42"})
    results = evaluate_checks(case, "The answer is 42.", RunStatus.SUCCESS.value)
    assert results["answer_contains"] is True


@pytest.mark.benchmark
def test_evaluate_checks_clarification():
    case = BenchmarkCase(
        id="t",
        query="q",
        category="trap",
        expected_checks={"must_ask_clarification": True},
    )
    results = evaluate_checks(case, "Which environment should I use?", RunStatus.NEEDS_CLARIFICATION.value)
    assert results["must_ask_clarification"] is True


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_direct_provider_mock():
    case = BenchmarkCase(
        id="simple-01",
        query="What is 2+2?",
        category="simple",
        expected_checks={"min_answer_length": 1},
    )
    result = await DirectProvider().run_case(case, MOCK_SPEC, mock=True)
    assert result.runner == RunnerKind.DIRECT
    assert result.calls_count == 1
    assert result.depth_level == 1
    assert result.latency_ms >= 0
    assert result.error is None


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_metis_pipeline_mock():
    case = BenchmarkCase(
        id="ambig-01",
        query="Should we use Python or JavaScript?",
        category="ambiguous",
        expected_checks={},
    )
    result = await MetisPipeline().run_case(case, MOCK_SPEC, mock=True)
    assert result.runner == RunnerKind.METIS
    assert result.calls_count >= 1
    assert result.depth_level >= 1
    assert result.error is None


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_benchmark_runner_mock():
    cases = load_dataset("simple")[:2]
    runner = BenchmarkRunner(runners=[RunnerKind.DIRECT, RunnerKind.METIS], mock=True)
    results = await runner.run_all(cases, MOCK_SPEC)
    assert len(results) == 4
    runners = {r.runner for r in results}
    assert RunnerKind.DIRECT in runners
    assert RunnerKind.METIS in runners


@pytest.mark.benchmark
def test_report_generation(tmp_path):
    from benchmarks.harness import CaseResult
    from benchmarks.report import render_markdown, write_report

    results = [
        CaseResult(
            case_id="simple-01",
            category="simple",
            runner=RunnerKind.DIRECT,
            model="mock",
            latency_ms=120.0,
            tokens_in=50,
            tokens_out=20,
            estimated_cost_usd=0.0,
            depth_level=1,
            calls_count=1,
            passed=True,
            check_results={"answer_contains": True},
            answer="4",
            status=RunStatus.SUCCESS.value,
        ),
        CaseResult(
            case_id="simple-01",
            category="simple",
            runner=RunnerKind.METIS,
            model="mock",
            latency_ms=800.0,
            tokens_in=500,
            tokens_out=100,
            estimated_cost_usd=0.001,
            depth_level=12,
            calls_count=5,
            passed=True,
            check_results={"answer_contains": True},
            answer="4",
            status=RunStatus.SUCCESS.value,
            route="council",
        ),
    ]
    out = tmp_path / "bench.md"
    path = write_report(results, out, dataset="simple", models=["mock"])
    md = path.read_text(encoding="utf-8")
    assert "Metis Benchmark Report" in md
    assert "direct" in md.lower()
    assert path.with_suffix(".json").exists()
    assert "Summary" in render_markdown(results, dataset="simple", models=["mock"])
