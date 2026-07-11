"""Benchmark harness — Direct API vs Metis pipeline."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

from metis.config import ModelSlot, ProviderKind, RouteMode, RuntimeConfig
from metis.economy.config import EconomyConfig, ModelPricing
from metis.economy.cost import CostCalculator, ROUTE_CALL_ESTIMATES
from metis.economy.meter import UsageMeter, set_current_meter
from metis.exoskeleton import Metis, RunStatus
from metis.models.provider import Message, create_provider
from metis.security import build_system_prompt

from benchmarks.providers import ModelSpec


class RunnerKind(str, Enum):
    DIRECT = "direct"
    METIS = "metis"


@dataclass
class BenchmarkCase:
    id: str
    query: str
    category: str
    expected_checks: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BenchmarkCase:
        return cls(
            id=str(data["id"]),
            query=str(data["query"]),
            category=str(data.get("category", "simple")),
            expected_checks=dict(data.get("checks", {})),
        )


@dataclass
class CaseResult:
    case_id: str
    category: str
    runner: RunnerKind
    model: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    depth_level: int
    calls_count: int
    passed: bool
    check_results: Dict[str, bool] = field(default_factory=dict)
    answer: str = ""
    status: str = ""
    route: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "runner": self.runner.value,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "depth_level": self.depth_level,
            "calls_count": self.calls_count,
            "passed": self.passed,
            "check_results": self.check_results,
            "answer": self.answer[:500],
            "status": self.status,
            "route": self.route,
            "error": self.error,
        }


class BenchmarkBackend(Protocol):
    async def run_case(self, case: BenchmarkCase, spec: ModelSpec) -> CaseResult:
        ...


def load_cases(path: Path) -> List[BenchmarkCase]:
    cases: List[BenchmarkCase] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(BenchmarkCase.from_dict(json.loads(line)))
    return cases


def load_dataset(name: str, datasets_dir: Optional[Path] = None) -> List[BenchmarkCase]:
    root = datasets_dir or Path(__file__).resolve().parent / "datasets"
    if name == "all":
        cases: List[BenchmarkCase] = []
        for path in sorted(root.glob("*.jsonl")):
            cases.extend(load_cases(path))
        return cases
    path = root / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return load_cases(path)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _tokens_from_usage(usage: Dict[str, Any], prompt: str, completion: str) -> tuple[int, int]:
    ti = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    to = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    if not ti:
        ti = _estimate_tokens(prompt)
    if not to:
        to = _estimate_tokens(completion)
    return ti, to


def evaluate_checks(case: BenchmarkCase, answer: str, status: str) -> Dict[str, bool]:
    results: Dict[str, bool] = {}
    checks = case.expected_checks
    text = answer or ""
    lower = text.lower()

    if "must_ask_clarification" in checks:
        want = bool(checks["must_ask_clarification"])
        got = status == RunStatus.NEEDS_CLARIFICATION.value or (
            "?" in text and any(
                kw in lower
                for kw in ("clarif", "which", "could you specify", "more detail", "уточн", "especif")
            )
        )
        results["must_ask_clarification"] = got == want

    if "answer_contains" in checks:
        needle = str(checks["answer_contains"]).lower()
        results["answer_contains"] = needle in lower

    if "answer_not_contains" in checks:
        needle = str(checks["answer_not_contains"]).lower()
        results["answer_not_contains"] = needle not in lower

    if "answer_regex" in checks:
        pattern = str(checks["answer_regex"])
        results["answer_regex"] = bool(re.search(pattern, text, re.IGNORECASE | re.DOTALL))

    if "status_success" in checks:
        want = bool(checks["status_success"])
        got = status == RunStatus.SUCCESS.value
        results["status_success"] = got == want

    if "min_answer_length" in checks:
        min_len = int(checks["min_answer_length"])
        results["min_answer_length"] = len(text.strip()) >= min_len

    return results


def _benchmark_config(spec: ModelSpec, *, mock: bool = False, route: RouteMode = RouteMode.COUNCIL) -> RuntimeConfig:
    economy = EconomyConfig(
        enabled=True,
        models={
            spec.model: ModelPricing(
                input_per_1m=spec.input_per_1m,
                output_per_1m=spec.output_per_1m,
                provider_label=spec.provider_label,
            )
        },
    )
    provider = ProviderKind.MOCK if mock else spec.provider
    return RuntimeConfig(
        allow_test_provider=mock,
        provider=provider,
        base_model=spec.model,
        base_url=spec.base_url,
        api_key=spec.api_key,
        default_route=route,
        economy=economy,
        enable_web_search=False,
        enable_code_interpreter=False,
        enable_long_term_memory=False,
        enable_mcp_tools=False,
        enforce_heterogeneous_agents=False,
        thinking_samples=1,
        max_verify_retries=1,
    )


class DirectProvider:
    """Single API call — no Metis orchestration."""

    async def run_case(self, case: BenchmarkCase, spec: ModelSpec, *, mock: bool = False) -> CaseResult:
        config = _benchmark_config(spec, mock=mock)
        slot = ModelSlot(
            name="direct",
            provider=config.provider,
            model=spec.model,
            base_url=spec.base_url,
            api_key=spec.api_key,
            temperature=0.3,
        )
        provider = create_provider(slot, config)
        system = build_system_prompt("You are a helpful assistant. Answer accurately and concisely.", "")
        prompt = case.query

        start = time.perf_counter()
        error: Optional[str] = None
        answer = ""
        status = RunStatus.SUCCESS.value
        tokens_in = 0
        tokens_out = 0
        cost = 0.0

        try:
            resp = await provider.complete(
                [Message("system", system), Message("user", prompt)],
                temperature=0.3,
            )
            answer = resp.content
            tokens_in, tokens_out = _tokens_from_usage(resp.usage, system + prompt, answer)
            meter = UsageMeter(route="direct")
            meter.record_llm(
                model=spec.model,
                provider=spec.provider_label,
                role="direct",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            cost = CostCalculator(config.economy).compute_report_cost(meter)
        except Exception as exc:
            error = str(exc)
            status = RunStatus.ERROR.value
        finally:
            if hasattr(provider, "aclose"):
                await provider.aclose()

        latency_ms = (time.perf_counter() - start) * 1000
        check_results = evaluate_checks(case, answer, status)
        passed = bool(check_results) and all(check_results.values())

        return CaseResult(
            case_id=case.id,
            category=case.category,
            runner=RunnerKind.DIRECT,
            model=spec.name,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=cost,
            depth_level=1,
            calls_count=1,
            passed=passed,
            check_results=check_results,
            answer=answer,
            status=status,
            route="direct",
            error=error,
        )


class MetisPipeline:
    """Full Metis exoskeleton with configurable route/depth."""

    def __init__(self, route: RouteMode = RouteMode.COUNCIL):
        self.route = route

    async def run_case(self, case: BenchmarkCase, spec: ModelSpec, *, mock: bool = False) -> CaseResult:
        config = _benchmark_config(spec, mock=mock, route=self.route)
        metis = Metis(config)

        start = time.perf_counter()
        error: Optional[str] = None
        answer = ""
        status = RunStatus.ERROR.value
        tokens_in = 0
        tokens_out = 0
        cost = 0.0
        calls_count = 0
        route_name = self.route.value

        try:
            result = await metis.run(case.query, route=self.route)
            answer = result.answer
            status = result.status.value
            route_name = result.route.value
            usage = result.metadata.get("usage", {})
            tokens_in = int(usage.get("total_tokens_in", 0))
            tokens_out = int(usage.get("total_tokens_out", 0))
            cost = float(usage.get("estimated_cost_usd", 0.0))
            calls_count = int(usage.get("event_count", 0))
            if not calls_count and tokens_in:
                calls_count = ROUTE_CALL_ESTIMATES.get(route_name, 1)
        except Exception as exc:
            error = str(exc)
            status = RunStatus.ERROR.value
        finally:
            set_current_meter(None)

        latency_ms = (time.perf_counter() - start) * 1000
        depth_level = ROUTE_CALL_ESTIMATES.get(route_name, calls_count or 1)
        check_results = evaluate_checks(case, answer, status)
        passed = bool(check_results) and all(check_results.values())

        return CaseResult(
            case_id=case.id,
            category=case.category,
            runner=RunnerKind.METIS,
            model=spec.name,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=cost,
            depth_level=depth_level,
            calls_count=calls_count or depth_level,
            passed=passed,
            check_results=check_results,
            answer=answer,
            status=status,
            route=route_name,
            error=error,
        )


class BenchmarkRunner:
    """Run benchmark cases against selected backends."""

    def __init__(
        self,
        *,
        runners: Optional[Iterable[RunnerKind]] = None,
        metis_route: RouteMode = RouteMode.COUNCIL,
        mock: bool = False,
    ):
        kinds = list(runners or [RunnerKind.DIRECT, RunnerKind.METIS])
        self.backends: Dict[RunnerKind, BenchmarkBackend] = {}
        if RunnerKind.DIRECT in kinds:
            self.backends[RunnerKind.DIRECT] = DirectProvider()
        if RunnerKind.METIS in kinds:
            self.backends[RunnerKind.METIS] = MetisPipeline(route=metis_route)
        self.mock = mock

    async def run_case(self, case: BenchmarkCase, spec: ModelSpec) -> List[CaseResult]:
        results: List[CaseResult] = []
        for kind, backend in self.backends.items():
            if isinstance(backend, DirectProvider):
                results.append(await backend.run_case(case, spec, mock=self.mock))
            elif isinstance(backend, MetisPipeline):
                results.append(await backend.run_case(case, spec, mock=self.mock))
            else:
                results.append(await backend.run_case(case, spec))
        return results

    async def run_all(self, cases: List[BenchmarkCase], spec: ModelSpec) -> List[CaseResult]:
        out: List[CaseResult] = []
        for case in cases:
            out.extend(await self.run_case(case, spec))
        return out
