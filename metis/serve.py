"""HTTP serve entrypoint for the OpenAI-compatible Metis API."""

from __future__ import annotations

import argparse
from pathlib import Path

from metis.config import RuntimeConfig


def serve_main() -> None:
    parser = argparse.ArgumentParser(
        description="Start Metis OpenAI-compatible API (no chat UI)",
    )
    parser.add_argument("--config", "-c", help="Path to runtime config YAML")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--production", action="store_true", help="Production mode (auth required)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn required. Install: pip install 'metis[distributed]'"
        ) from exc

    from metis.api.app import create_app

    cfg = RuntimeConfig.from_yaml(args.config) if args.config else RuntimeConfig()
    if args.production:
        cfg.production = True

    app = create_app(cfg)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    serve_main()
