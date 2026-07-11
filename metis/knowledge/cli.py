"""CLI: metis knowledge export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metis.knowledge.store import KnowledgeStore


def run_knowledge_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Metis knowledge commands")
    sub = parser.add_subparsers(dest="cmd", required=True)

    export = sub.add_parser("export", help="Export verified experiences as JSONL for offline SFT")
    export.add_argument("-o", "--output", default="knowledge_export.jsonl")
    export.add_argument("--store", default="data/knowledge")
    export.add_argument("--no-feedback", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "export":
        store = KnowledgeStore(Path(args.store))
        records = store.export_jsonl(include_feedback=not args.no_feedback)
        out = Path(args.output)
        with out.open("w") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"Exported {len(records)} records to {out}")
        return 0
    return 1
