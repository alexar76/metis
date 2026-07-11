"""Ecosystem provider surface for Metis — the *verification envelope* endpoints.

Two routes, one handler, zero coupling:

* ``POST /v1/verify`` — run any input through Metis's cognitive stack and return
  the full verification envelope ``{answer, status, verify_score, verified,
  route, clarifications, usage, depth, trace_id}``. This is what a *consumer*
  (e.g. the AICOM factory confidence-gate) calls to turn "trust one LLM call"
  into "deliberate → verify → get a confidence score → gate or ask".

* ``POST /aimarket/invoke`` — the AIMarket Hub capability contract. The hub
  POSTs ``{input, product_id, capability_id}`` to a capability's ``invoke_url``
  and reads ``payload["result"]`` back (see aimarket-hub api.py). This route
  wraps the same envelope in ``{"result": <envelope>}`` so a Metis deployment
  can be registered as an invocable, billable hub capability.

Both routes are **optional**: mounting this router adds endpoints but changes
nothing else, and Metis serves normally without it. The router imports **only**
Metis internals — never any ecosystem package — so a standalone Metis has no
dependency on the hub, the factory, or the monitor.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from metis.api.auth import verify_api_key
from metis.api.bridge import messages_to_query
from metis.config import RouteMode, RuntimeConfig
from metis.exoskeleton import ExoskeletonResult, Metis, RunStatus

logger = logging.getLogger("metis.api.ecosystem")

router = APIRouter()

# Default "verified" threshold. Callers may override per request via
# ``min_verify_score``; the raw ``verify_score`` is always returned so a
# consumer can apply its own policy regardless.
DEFAULT_VERIFY_PASS = 0.7

# Hard cap on the flattened query length accepted here (defence in depth on top
# of the config's ``security.max_user_input_chars``).
_MAX_INPUT_CHARS = 200_000

# Server-side wall-clock cap so a client disconnect can't orphan expensive work.
_RUN_TIMEOUT = 180.0


def _rate_limit(request: Request, api_key: str | None = None) -> None:
    """Per-client rate limit on the expensive cognition routes (cheap DoS guard).

    Uses the limiter attached to ``app.state.eco_limiter`` in create_app; no-op
    when absent (e.g. bare test apps). When an API key is available, it is used as
    the bucket key instead of IP, so paying users behind the same NAT don't share
    one limit."""
    lim = getattr(request.app.state, "eco_limiter", None)
    if lim is None:
        return
    key = api_key or (request.client.host if request.client else "unknown")
    ok, retry = lim.allow(lim.client_key(key))
    if not ok:
        raise HTTPException(status_code=429, detail=f"rate limit exceeded, retry in {retry}s")


class VerifyRequest(BaseModel):
    """Generic verified-cognition request (consumer side, e.g. factory gate)."""

    input: Any = Field(..., description="A string, or {messages|query|prompt|text}, or any JSON.")
    route: Optional[str] = Field(None, description="fast|thinking|council|agent — omit to auto-route.")
    min_verify_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Threshold for the convenience `verified` flag."
    )


class InvokeRequest(BaseModel):
    """AIMarket Hub capability-invoke contract."""

    input: Any = Field(..., description="Opaque input forwarded by the hub.")
    product_id: Optional[str] = None
    capability_id: Optional[str] = None
    route: Optional[str] = None


def _extract_images(raw: Any, cfg: RuntimeConfig) -> List[str]:
    """Pull validated image URLs from an invoke payload (messages[] or images[])."""
    if not getattr(cfg, "enable_multimodal", True) or not isinstance(raw, dict):
        return []
    from metis.api.bridge import extract_images
    from metis.security.media import validate_images

    max_n = getattr(cfg, "max_images", 5)
    if isinstance(raw.get("messages"), list):
        return extract_images(raw["messages"], max_n)
    imgs = raw.get("images")
    if isinstance(imgs, list):
        return validate_images([str(u) for u in imgs], max_images=max_n)
    return []


def _coerce_query(raw: Any) -> str:
    """Flatten an arbitrary invoke payload into a single query string."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("messages"), list):
            return messages_to_query(raw["messages"])
        for key in ("query", "prompt", "text", "question", "task"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return json.dumps(raw, ensure_ascii=False)


def _parse_route(route: Optional[str]) -> Optional[RouteMode]:
    if not route:
        return None
    try:
        return RouteMode(route.strip().lower())
    except ValueError as exc:  # noqa: PERF203 — explicit 400 is clearer than a 500
        raise HTTPException(status_code=400, detail=f"invalid route: {route}") from exc


def _config(request: Request) -> RuntimeConfig:
    cfg = getattr(request.app.state, "config", None)
    return cfg if isinstance(cfg, RuntimeConfig) else RuntimeConfig()


def _envelope(result: ExoskeletonResult, *, min_score: float) -> Dict[str, Any]:
    score = float(result.verify_score or 0.0)
    status = result.status.value
    depth = getattr(result, "depth", None)
    meta = result.metadata or {}
    clar: List[str] = list(result.clarifications or [])
    return {
        "answer": result.answer,
        "status": status,
        "verified": status == RunStatus.SUCCESS.value and score >= min_score,
        "verify_score": round(score, 4),
        "route": result.route.value,
        "depth": getattr(depth, "value", None),
        "iterations": getattr(result, "iterations", 0),
        "clarifications": clar,
        "usage": meta.get("usage", {}),
        "trace_id": meta.get("trace_id"),
    }


async def _run_envelope(
    request: Request,
    *,
    raw_input: Any,
    route: Optional[str],
    min_score: float,
    api_key: str | None = None,
) -> Dict[str, Any]:
    """Shared handler: run one stateless Metis pass and build the envelope.

    Never raises for provider/LLM failures — returns an ``error`` envelope so
    callers get a clean, machine-readable result (and no stack trace leaks).
    """
    query = _coerce_query(raw_input)
    if not query.strip():
        raise HTTPException(status_code=400, detail="input is empty")
    if len(query) > _MAX_INPUT_CHARS:
        raise HTTPException(status_code=413, detail="input too large")

    mode = _parse_route(route)
    cfg = _config(request)
    _rate_limit(request, api_key)  # cheap DoS guard on the expensive cognition routes
    images = _extract_images(raw_input, cfg)
    # Fresh, stateless instance per request (no cross-request working-memory
    # bleed) — the same pattern coordinator_server.py uses for /v1/query.
    brain = Metis(cfg)
    timeout_s = float(getattr(cfg.security, "request_timeout_seconds", 0) or _RUN_TIMEOUT)
    try:
        result = await asyncio.wait_for(
            brain.run(query, route=mode, images=images or None), timeout=timeout_s
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        logger.warning("metis verify run timed out after %ss", timeout_s)
        return {
            "answer": "", "status": RunStatus.ERROR.value, "verified": False,
            "verify_score": 0.0, "route": (mode or cfg.default_route).value,
            "depth": None, "iterations": 0, "clarifications": [], "usage": {},
            "trace_id": None, "error": "timeout",
        }
    except Exception as exc:  # pragma: no cover - defensive; keeps the endpoint fail-safe
        # Log only the exception TYPE — a raw provider error can embed secrets.
        logger.warning("metis verify run failed: %s", type(exc).__name__)
        return {
            "answer": "",
            "status": RunStatus.ERROR.value,
            "verified": False,
            "verify_score": 0.0,
            "route": (mode or cfg.default_route).value,
            "depth": None,
            "iterations": 0,
            "clarifications": [],
            "usage": {},
            "trace_id": None,
            "error": type(exc).__name__,
        }
    return _envelope(result, min_score=min_score)


@router.post("/v1/verify")
async def verify_endpoint(
    body: VerifyRequest,
    request: Request,
    _api_key: Optional[str] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Verified cognition for ecosystem consumers (e.g. the factory gate)."""
    min_score = body.min_verify_score if body.min_verify_score is not None else DEFAULT_VERIFY_PASS
    return await _run_envelope(
        request, raw_input=body.input, route=body.route, min_score=min_score,
        api_key=_api_key,
    )


def _sse(event: str, data: Dict[str, Any]) -> str:
    """Format one Server-Sent-Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Cadence of the keep-alive comment during multi-second gaps (nginx idle guard).
_SSE_TICK = 0.5


@router.post("/v1/verify/stream")
async def verify_stream_endpoint(
    body: VerifyRequest,
    request: Request,
    _api_key: Optional[str] = Depends(verify_api_key),
) -> StreamingResponse:
    """Stream Metis's cognition **live** as Server-Sent Events.

    Runs one stateless pass and emits the *real* pipeline events as they happen
    (``route_selected`` → ``council_started`` → ``confidence_gate`` → MoA layers
    → ``verify_pass``/``verify_fail`` …), then a terminal ``done`` frame carrying
    the full verification envelope (incl. ``verify_score`` + ``usage``). This is
    what the landing "cognition panel" and the reactive star consume. It reuses
    the same auth, rate limit, coercion and envelope as ``/v1/verify`` — the only
    difference is the transport. Entirely optional & self-contained.
    """
    _rate_limit(request, _api_key)  # cheap DoS guard, before we commit to a stream
    query = _coerce_query(body.input)
    if not query.strip():
        raise HTTPException(status_code=400, detail="input is empty")
    if len(query) > _MAX_INPUT_CHARS:
        raise HTTPException(status_code=413, detail="input too large")

    mode = _parse_route(body.route)
    cfg = _config(request)
    images = _extract_images(body.input, cfg)
    min_score = body.min_verify_score if body.min_verify_score is not None else DEFAULT_VERIFY_PASS
    brain = Metis(cfg)
    timeout_s = float(getattr(cfg.security, "request_timeout_seconds", 0) or _RUN_TIMEOUT)

    async def gen():
        q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()

        def sink(record: Dict[str, Any]) -> None:
            # Called synchronously from deep in the pipeline (inside the run
            # task's context). Non-blocking; drops nothing in practice.
            try:
                q.put_nowait(record)
            except Exception:  # pragma: no cover - defensive
                pass

        yield _sse("start", {"route_hint": (mode or cfg.default_route).value})

        task = asyncio.create_task(
            asyncio.wait_for(
                brain.run(query, route=mode, images=images or None, on_event=sink),
                timeout=timeout_s,
            )
        )
        try:
            while not (task.done() and q.empty()):
                try:
                    rec = await asyncio.wait_for(q.get(), timeout=_SSE_TICK)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # comment frame; keeps the socket warm
                    continue
                yield _sse(str(rec.get("pipeline_event", "pipeline")), rec)
            result = await task
            yield _sse("done", _envelope(result, min_score=min_score))
        except asyncio.TimeoutError:
            yield _sse("error", {"error": "timeout"})
        except Exception as exc:  # pragma: no cover - defensive; type only, no secrets
            logger.warning("metis verify stream failed: %s", type(exc).__name__)
            yield _sse("error", {"error": type(exc).__name__})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx: do not buffer this response
        },
    )


@router.post("/aimarket/invoke")
async def aimarket_invoke(
    body: InvokeRequest,
    request: Request,
    _api_key: Optional[str] = Depends(verify_api_key),
    x_aimarket_sandbox: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """AIMarket Hub capability contract — returns ``{"result": <envelope>}``.

    Sandbox invokes (``X-AIMarket-Sandbox: 1``) are forced onto the cheap
    ``fast`` route so catalog probes never spend a full council budget.
    """
    route = body.route
    if (x_aimarket_sandbox or "").strip() == "1":
        route = RouteMode.FAST.value  # sandbox probes ALWAYS use the cheap route
    envelope = await _run_envelope(
        request, raw_input=body.input, route=route, min_score=DEFAULT_VERIFY_PASS,
        api_key=_api_key,
    )
    return {
        "result": envelope,
        "product_id": body.product_id,
        "capability_id": body.capability_id,
    }
