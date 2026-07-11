"""CLI for observability: trace, tail, stats."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from metis.observability.trace_store import TraceStore


def _default_trace_dir() -> Path:
    return Path("data/traces")


def _log_file_paths() -> List[Path]:
    paths: List[Path] = []
    env = os.environ.get("METIS_LOG_FILE")
    if env:
        paths.append(Path(env))
    default = Path("data/logs/metis.jsonl")
    if default.exists():
        paths.append(default)
    return paths


def _iter_jsonl(path: Path, *, follow: bool = False) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open(encoding="utf-8") as f:
        if follow:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    yield line.rstrip("\n")
                else:
                    time.sleep(0.25)
        else:
            for line in f:
                yield line.rstrip("\n")


def _cmd_trace(args: argparse.Namespace) -> int:
    store = TraceStore(Path(args.dir))
    rec = store.get(args.trace_id)
    if rec:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0

    found = 0
    for path in _log_file_paths():
        for line in _iter_jsonl(path):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("trace_id") == args.trace_id:
                print(json.dumps(entry, indent=2, ensure_ascii=False))
                found += 1
    if found:
        print(f"\n--- {found} log entries ---", file=sys.stderr)
        return 0
    print(f"Trace not found: {args.trace_id}", file=sys.stderr)
    return 1


def _cmd_tail(args: argparse.Namespace) -> int:
    if args.follow:
        paths = _log_file_paths()
        if not paths:
            print("No log file. Set METIS_LOG_FILE.", file=sys.stderr)
            return 1
        print(f"Following {paths[0]} (Ctrl+C to stop)", file=sys.stderr)
        try:
            for line in _iter_jsonl(paths[0], follow=True):
                print(line)
        except KeyboardInterrupt:
            pass
        return 0

    store = TraceStore(Path(args.dir))
    records = store.tail(args.n)
    for rec in records:
        print(json.dumps(rec, ensure_ascii=False))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    store = TraceStore(Path(args.dir))
    stats = store.stats()
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0
    print(f"Total traces: {stats['total']}")
    print(f"Module calls: {stats.get('module_calls', 0)}")
    print(f"Module errors: {stats.get('module_errors', 0)} ({stats.get('failure_rate_pct', 0)}%)")
    if stats.get("by_module"):
        print("\nBy module:")
        for role, count in sorted(stats["by_module"].items(), key=lambda x: -x[1]):
            print(f"  {role}: {count}")
    if stats.get("by_endpoint"):
        print("\nBy endpoint:")
        for ep, count in sorted(stats["by_endpoint"].items(), key=lambda x: -x[1]):
            print(f"  {ep}: {count}")
    if stats.get("failures_by_kind"):
        print("\nFailures by kind:")
        for kind, count in stats["failures_by_kind"].items():
            print(f"  {kind}: {count}")
    return 0


def run_logs_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Metis observability logs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    trace = sub.add_parser("trace", help="Fetch trace by ID (redacted)")
    trace.add_argument("trace_id")
    trace.add_argument("--dir", default=str(_default_trace_dir()))

    tail = sub.add_parser("tail", help="Tail structured logs or recent traces")
    tail.add_argument("-n", type=int, default=20)
    tail.add_argument("--dir", default=str(_default_trace_dir()))
    tail.add_argument("-f", "--follow", action="store_true", help="Follow log file")

    stats = sub.add_parser("stats", help="Failure rates per module/endpoint")
    stats.add_argument("--json", action="store_true")
    stats.add_argument("--dir", default=str(_default_trace_dir()))

    args = parser.parse_args(argv)
    if args.cmd == "trace":
        return _cmd_trace(args)
    if args.cmd == "tail":
        return _cmd_tail(args)
    if args.cmd == "stats":
        return _cmd_stats(args)
    return 1


# Backward-compatible alias
run_observability_cli = run_logs_cli
