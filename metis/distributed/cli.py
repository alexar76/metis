"""CLI for distributed cluster operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

from metis.config import ProviderKind
from metis.distributed.registry import NodeRegistry
from metis.distributed.security import SecuritySettings, resolve_api_key


def cluster_status_main() -> None:
    parser = argparse.ArgumentParser(description="Check health of metis cluster nodes")
    parser.add_argument("--config", "-c", required=True, help="Path to cluster_config.yaml")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    args = parser.parse_args()

    registry = NodeRegistry.from_yaml(args.config)
    report = asyncio.run(_status(registry))

    if args.json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Coordinator: {report.get('coordinator_url', 'n/a')}")
        print(f"Healthy: {report.get('healthy_count', 0)}/{report.get('total_count', 0)}")
        for node in report.get("nodes", []):
            status = node.get("status", "unknown")
            latency = node.get("latency_ms")
            lat_str = f" ({latency:.0f}ms)" if latency is not None else ""
            err = f" — {node['error']}" if node.get("error") else ""
            print(f"  [{status}] {node['id']} @ {node['url']}{lat_str}{err}")

    unhealthy = report.get("healthy_count", 0) < report.get("total_count", 0)
    sys.exit(1 if unhealthy and report.get("total_count", 0) > 0 else 0)


async def _status(registry: NodeRegistry) -> Dict[str, Any]:
    await registry.check_health()
    report = registry.status_report()
    report["healthy_count"] = len(registry.healthy_nodes())
    report["total_count"] = len(registry.all_nodes())
    return report


def node_serve_main() -> None:
    parser = argparse.ArgumentParser(description="Start a metis worker node")
    parser.add_argument("--config", "-c", help="Path to node_config.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--node-id", default="local-node")
    parser.add_argument("--production", action="store_true", help="Production mode (auth required)")
    args = parser.parse_args()

    cfg: Dict[str, Any] = {}
    if args.config:
        with open(args.config) as f:
            cfg = yaml.safe_load(f) or {}

    from metis.distributed.server import serve_node

    provider_name = cfg.get("provider", "ollama")
    provider = ProviderKind(provider_name)
    security_data = cfg.get("security", {})
    security = SecuritySettings(**security_data) if security_data else None
    llm_key = resolve_api_key(cfg.get("llm_api_key_env"), fallback=cfg.get("api_key", "ollama"))

    serve_node(
        host=cfg.get("host", args.host),
        port=int(cfg.get("port", args.port)),
        node_id=cfg.get("node_id", args.node_id),
        models=cfg.get("models"),
        roles=cfg.get("roles"),
        provider=provider,
        model=cfg.get("model", "qwen3:8b"),
        base_url=os.environ.get("METIS_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or cfg.get("base_url", "http://localhost:11434/v1"),
        api_key=llm_key,
        api_key_env=cfg.get("api_key_env"),
        security=security,
        production=args.production or cfg.get("production", False),
    )


def coordinator_serve_main() -> None:
    parser = argparse.ArgumentParser(description="Start metis coordinator HTTP API")
    parser.add_argument("--config", "-c", help="Path to runtime config YAML")
    parser.add_argument("--cluster", help="Path to cluster_config.yaml (sets distributed mode)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--production", action="store_true", help="Production mode (auth required)")
    args = parser.parse_args()

    from pathlib import Path

    from metis.coordinator_server import create_coordinator_app, _require_fastapi
    from metis.config import RuntimeConfig

    _, uvicorn = _require_fastapi()

    if args.config:
        cfg = RuntimeConfig.from_yaml(args.config)
        if args.cluster:
            cfg.distributed = True
            cfg.cluster_config = Path(args.cluster)
        if args.production:
            cfg.production = True
        app = create_coordinator_app(config=cfg, production=args.production or cfg.production)
    else:
        app = create_coordinator_app(config_path=args.config, production=args.production)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    cluster_status_main()
