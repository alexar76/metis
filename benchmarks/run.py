"""CLI entry point for Metis benchmarks."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List

from metis.config import RouteMode

from benchmarks.harness import BenchmarkRunner, RunnerKind, load_dataset
from benchmarks.providers import available_models, resolve_model_spec, skipped_models
from benchmarks.report import write_report


def _parse_models(raw: str) -> List[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


def _parse_compare(raw: str) -> List[RunnerKind]:
    kinds: List[RunnerKind] = []
    for part in raw.split(","):
        part = part.strip().lower()
        if part == "direct":
            kinds.append(RunnerKind.DIRECT)
        elif part == "metis":
            kinds.append(RunnerKind.METIS)
    return kinds or [RunnerKind.DIRECT, RunnerKind.METIS]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Metis benchmark suite — Direct vs Metis")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run benchmark suite")
    run.add_argument("--models", default="qwen3:8b", help="Comma-separated model ids")
    run.add_argument("--dataset", default="all", help="Dataset name or 'all'")
    run.add_argument(
        "--compare",
        default="direct,metis",
        help="Runners to compare: direct,metis",
    )
    run.add_argument("--output", "-o", help="Report path (.md); JSON written alongside")
    run.add_argument("--route", choices=[m.value for m in RouteMode], default="council")
    run.add_argument(
        "--mock",
        action="store_true",
        help="Offline mode with test mock provider (CI only)",
    )
    run.add_argument("--datasets-dir", help="Override datasets directory")

    sub.add_parser("list-models", help="List models available with current env keys")
    sub.add_parser("list-datasets", help="List benchmark datasets")

    return parser


async def _run_benchmarks(args: argparse.Namespace) -> int:
    if args.mock:
        models = _parse_models(args.models) or ["qwen3:8b"]
    else:
        requested = _parse_models(args.models)
        models = [m for m in requested if resolve_model_spec(m)]
        skip = skipped_models(requested)
        if skip:
            print(f"Skipping models (no API key): {', '.join(skip)}", file=sys.stderr)
        if not models:
            print("No models available. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, or use --mock.", file=sys.stderr)
            return 0

    datasets_dir = Path(args.datasets_dir) if args.datasets_dir else None
    cases = load_dataset(args.dataset, datasets_dir=datasets_dir)
    runners = _parse_compare(args.compare)
    route = RouteMode(args.route)
    runner = BenchmarkRunner(runners=runners, metis_route=route, mock=args.mock)

    all_results = []
    for model in models:
        spec = resolve_model_spec(model)
        if not spec and not args.mock:
            continue
        if args.mock:
            from benchmarks.providers import ModelSpec
            from metis.config import ProviderKind

            spec = ModelSpec(
                name=model,
                model=model,
                provider=ProviderKind.MOCK,
                base_url="mock://local",
                api_key="mock",
                provider_label="mock",
            )
        print(f"Running {len(cases)} cases — model={model} runners={[r.value for r in runners]}", file=sys.stderr)
        all_results.extend(await runner.run_all(cases, spec))

    if args.output:
        out = Path(args.output)
    else:
        from datetime import datetime

        out = Path("reports") / f"bench-{datetime.now().strftime('%Y%m%d')}.md"

    skipped = skipped_models(_parse_models(args.models)) if not args.mock else []
    path = write_report(
        all_results,
        out,
        dataset=args.dataset,
        models=models,
        skipped=skipped or None,
    )
    print(f"Report written: {path}")
    print(f"JSON written: {path.with_suffix('.json')}")
    return 0


def cmd_list_models() -> int:
    avail = available_models(include_without_keys=True)
    ready = available_models(include_without_keys=False)
    for name in avail:
        status = "ready" if name in ready else "needs API key"
        print(f"{name}\t{status}")
    return 0


def cmd_list_datasets() -> int:
    root = Path(__file__).resolve().parent / "datasets"
    for path in sorted(root.glob("*.jsonl")):
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        print(f"{path.stem}\t{count} cases")
    return 0


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        code = asyncio.run(_run_benchmarks(args))
        sys.exit(code)
    if args.command == "list-models":
        sys.exit(cmd_list_models())
    if args.command == "list-datasets":
        sys.exit(cmd_list_datasets())

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
