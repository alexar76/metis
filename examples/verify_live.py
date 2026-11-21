#!/usr/bin/env python3
"""Five-minute live check against Metis /v1/verify.

    python3 examples/verify_live.py
    python3 examples/verify_live.py "What is 2+2? Reply with only the number."

Environment (pick one bearer for the live node):

    AIMARKET_METIS_KEY   preferred (same name aimarket-mcp uses)
    METIS_API_KEY        alias

Optional:

    AIMARKET_METIS_URL   default https://metis.modelmarket.dev

The public demo at https://metis.modelmarket.dev requires a bearer for
/v1/verify. Without a key this script exits non-zero and prints the 401 detail
instead of inventing a score.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://metis.modelmarket.dev"
DEFAULT_PROMPT = "What is 2+2? Reply with only the number."


def main(argv: list[str]) -> int:
    base = os.environ.get("AIMARKET_METIS_URL", DEFAULT_URL).rstrip("/")
    key = os.environ.get("AIMARKET_METIS_KEY") or os.environ.get("METIS_API_KEY") or ""
    prompt = argv[1] if len(argv) > 1 else DEFAULT_PROMPT

    body = json.dumps({"input": prompt, "route": "fast"}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(f"{base}/v1/verify", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} from {base}/v1/verify", file=sys.stderr)
        print(detail[:500], file=sys.stderr)
        if exc.code in (401, 403) and not key:
            print(
                "Set AIMARKET_METIS_KEY (or METIS_API_KEY) for the live node.",
                file=sys.stderr,
            )
        return 1
    except Exception as exc:  # noqa: BLE001 — show any transport failure plainly
        print(f"request failed: {exc}", file=sys.stderr)
        return 1

    score = payload.get("verify_score")
    verified = payload.get("verified")
    answer = payload.get("answer") or payload.get("output") or ""
    if isinstance(answer, str) and len(answer) > 240:
        answer = answer[:237] + "..."

    print(f"endpoint: {base}/v1/verify")
    print(f"verify_score: {score}")
    print(f"verified: {verified}")
    print(f"answer: {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
