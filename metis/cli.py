"""CLI for metis."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from metis.config import ProviderKind, RouteMode, RuntimeConfig
from metis.exoskeleton import Metis, RunStatus
from metis.modules.registry import ModuleRegistry


def _load_config(path: str | None) -> RuntimeConfig:
    return RuntimeConfig.from_yaml(path) if path else RuntimeConfig()


def _cmd_config_validate(config: RuntimeConfig, *, json_out: bool) -> int:
    result = ModuleRegistry(config).validate()

    for warning in result.warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if json_out:
        print(json.dumps({
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "module_count": len(result.resolved),
        }, indent=2))
    else:
        status = "valid" if result.valid else "invalid"
        print(f"Config {status}: {len(result.resolved)} modules resolved")
        if result.errors:
            print(f"  {len(result.errors)} error(s)")
        if result.warnings:
            print(f"  {len(result.warnings)} warning(s)")

    return 0 if result.valid else 1


def _cmd_config_show_modules(config: RuntimeConfig, *, json_out: bool) -> int:
    rows = ModuleRegistry(config).show_modules()

    if json_out:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"{'ROLE':<28} {'MODEL':<24} {'ENDPOINT':<36} {'SOURCE'}")
    print("-" * 100)
    for row in rows:
        print(
            f"{row['role']:<28} {row['model']:<24} {row['endpoint']:<36} {row['source']}"
        )
    return 0


def _run_config_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Metis config commands")
    sub = parser.add_subparsers(dest="config_cmd", required=True)

    validate = sub.add_parser("validate", help="Validate module config resolves")
    validate.add_argument("--config", "-c", help="Path to config YAML")
    validate.add_argument("--json", action="store_true", dest="json_out")

    show = sub.add_parser("show-modules", help="List role → model → endpoint")
    show.add_argument("--config", "-c", help="Path to config YAML")
    show.add_argument("--json", action="store_true", dest="json_out")

    args = parser.parse_args(argv)
    config = _load_config(args.config)

    if args.config_cmd == "validate":
        return _cmd_config_validate(config, json_out=args.json_out)
    if args.config_cmd == "show-modules":
        return _cmd_config_show_modules(config, json_out=args.json_out)
    return 1


def _cmd_query(args: argparse.Namespace) -> int:
    if not args.query:
        print("ERROR: query required", file=sys.stderr)
        return 1

    config = _load_config(args.config)
    if args.production:
        config.production = True
    if args.cluster:
        config.distributed = True
        config.cluster_config = Path(args.cluster)
    if args.model:
        config.base_model = args.model
    if args.url:
        config.base_url = args.url

    if config.production and config.provider == ProviderKind.MOCK:
        print("ERROR: Mock provider not allowed in production mode", file=sys.stderr)
        return 2

    route = RouteMode(args.route) if args.route else None
    result = asyncio.run(Metis(config).run(args.query, route=route))

    if args.json_out:
        print(json.dumps({
            "answer": result.answer,
            "status": result.status.value,
            "route": result.route.value,
            "verify_score": result.verify_score,
            "clarifications": result.clarifications,
            "task_spec": result.task_spec.model_dump() if result.task_spec else None,
            "metadata": result.metadata,
        }, ensure_ascii=False, indent=2))
    else:
        if result.status == RunStatus.NEEDS_CLARIFICATION:
            print("Need clarification:")
            for q in result.clarifications:
                print(f"  - {q}")
        else:
            if result.task_spec:
                print(f"[route={result.route.value} confidence={result.task_spec.confidence:.2f}]\n")
            print(result.answer)

    return 0 if result.status != RunStatus.ERROR else 1


def _run_calibrate_cli(argv: list[str]) -> int:
    """`metis calibrate` — measure each configured model's capability and write the scores
    the capability gate reads. Real calls, no stub."""
    p = argparse.ArgumentParser(prog="metis calibrate",
                                description="Measure configured models' capability; write scores for the gate")
    p.add_argument("--config", "-c", help="Path to config YAML")
    p.add_argument("--out", "-o", default=None, help="Where to write scores (default: config.capability_file)")
    p.add_argument("--json", action="store_true", dest="json_out")
    a = p.parse_args(argv)

    config = _load_config(a.config)
    from metis.agents.capability import calibrate_pool, tier_of
    pool = ModuleRegistry(config)._reasoning_pool()
    if not pool:
        print("No models configured to calibrate.", file=sys.stderr)
        return 1
    print(f"Calibrating {len(pool)} model(s) on the built-in checkable set…", file=sys.stderr)
    scores = asyncio.run(calibrate_pool(pool, config))

    out = Path(a.out) if a.out else Path(config.capability_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scores, indent=2))

    if a.json_out:
        print(json.dumps(scores, indent=2))
    else:
        print(f"{'MODEL':<40} {'SCORE':>6}  TIER")
        print("-" * 60)
        for m, s in sorted(scores.items(), key=lambda kv: -kv[1]):
            print(f"{m:<40} {s:>6}  {tier_of(s).value}")
        print(f"\nWrote {len(scores)} score(s) → {out}", file=sys.stderr)
    return 0


def main() -> None:
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "config":
            sys.exit(_run_config_cli(sys.argv[2:]))
        if cmd == "calibrate":
            sys.exit(_run_calibrate_cli(sys.argv[2:]))
        if cmd == "logs":
            from metis.observability.cli import run_logs_cli
            sys.exit(run_logs_cli(sys.argv[2:]))
        if cmd == "knowledge":
            from metis.knowledge.cli import run_knowledge_cli
            sys.exit(run_knowledge_cli(sys.argv[2:]))

    parser = argparse.ArgumentParser(description="Metis — multi-agent reasoning orchestrator")
    parser.add_argument("query", nargs="?", help="User query")
    parser.add_argument("--config", "-c", help="Path to config YAML")
    parser.add_argument("--cluster", help="Path to cluster_config.yaml")
    parser.add_argument("--route", choices=[m.value for m in RouteMode], help="Force route mode")
    parser.add_argument("--model", help="Base model name")
    parser.add_argument("--url", help="API base URL")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    parser.add_argument("--production", action="store_true", help="Production mode (strict security)")

    args = parser.parse_args()
    if not args.query:
        parser.print_help()
        sys.exit(1)
    sys.exit(_cmd_query(args))


if __name__ == "__main__":
    main()
