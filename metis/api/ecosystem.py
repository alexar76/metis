"""Ecosystem provider surface for Metis — the *verification envelope* endpoints.

Two routes, one handler, zero coupling:

* ``POST /v1/verify`` — run any input through Metis's cognitive stack and return
  the full verification envelope ``{answer, status, verify_score, verified,
  verify_performed, threshold, route, clarifications, usage, depth, trace_id}``. This is
  what a *consumer* (e.g. the AICOM factory confidence-gate) calls to turn
  "trust one LLM call" into "deliberate → verify → get a confidence score →
  gate or ask".

  The verify endpoints **guarantee** the score is real: the ``fast`` and
  ``thinking`` routes are a single provider call and leave ``verify_score`` at
  its 0.0 default because no verifier runs on them, so these endpoints run the
  critic over the produced answer before answering. ``verify_performed`` says
  whether a verifier actually scored the answer — a consumer that moves money on
  the verdict (the hub's Pay-on-Verified escrow) must not read "nothing was
  verified" as "the work failed".

  That guarantee costs a second provider call on those two routes. It is on by
  default and switched off only by an explicit ``METIS_VERIFY_GUARANTEE=0`` (see
  ``verify_guarantee_enabled``); switched off, the endpoint reports the unscored run
  honestly rather than inventing a number.

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
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from metis.api.auth import verify_api_key
from metis.api.bridge import messages_to_query
from metis.config import DEFAULT_REQUEST_TIMEOUT_SECONDS, RouteMode, RuntimeConfig
from metis.exoskeleton import ExoskeletonResult, Metis, RunStatus
from metis.schemas.task_spec import TaskSpec
from metis.verify.critic import clamp_score, verify_answer

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
# SecurityConfig may lower this per deployment, but never raise it beyond the
# canonical ceiling without a code/config review of every upstream proxy.
_RUN_TIMEOUT = DEFAULT_REQUEST_TIMEOUT_SECONDS

# Floor for the guaranteed-verification pass when the main run already ate most
# of the request budget: a judge call that is refused for lack of time reports
# verify_performed=False, which is *worse* for the caller than one extra second.
_VERIFY_PASS_MIN_BUDGET_S = 10.0

# …but that floor is time the caller was never promised. `request_timeout_seconds`
# is the deadline /v1/verify advertises, and granting the floor unconditionally let
# a run that had already consumed the whole budget push the response arbitrarily
# past it (the run is time-boxed, so the excess was small in practice, but it was
# never *stated* anywhere and nothing bounded it). So the overrun is now explicit:
# the forced critic may finish inside whatever budget is left, and when the budget
# is gone it may borrow at most this much beyond the deadline — after which it is
# refused outright and the envelope says `verify_performed: false` (indeterminate to
# a money gate, never a fault). Hard invariant, asserted in the tests:
#
#   elapsed_s + granted_budget <= timeout_s + _VERIFY_PASS_MAX_OVERRUN_S
_VERIFY_PASS_MAX_OVERRUN_S = 10.0

# The synthesised TaskSpec's goal is echoed into the judge prompt alongside the
# original query; cap it so a 200k-char audit request is not paid for twice.
_JUDGE_GOAL_CHARS = 2000

# Generic success criteria for the routes that carry no council-built TaskSpec.
_ANSWER_CRITERIA = (
    "The answer addresses the request directly and completely",
    "The answer is internally consistent and makes no unsupported claims",
    "The answer obeys any output format the request demands",
)

# ── The verification guarantee's cost knob ────────────────────────────────────
#
# On the ``fast``/``thinking`` routes the guarantee is a SECOND provider call (the
# run, then the critic). That is the right trade for a verdict a consumer can move
# money on, but it doubles the per-request bill on the cheap routes, so it must be a
# decision an operator can see and take — not a surprise on an invoice.
#
# Default ON, and only an explicit 0/false/no/off turns it off: a value that parses
# as NEITHER boolean is a typo, and reading a typo as "stop verifying" would silently
# return /v1/verify to answering "success, nothing verified" — the exact envelope the
# hub's escrow classifies as indeterminate. Same convention (and the same reasoning)
# as the hub's AIMARKET_VERIFY_FAIL_CLOSED.
_GUARANTEE_ENV = "METIS_VERIFY_GUARANTEE"
_FALSEY_TOKENS = ("0", "false", "no", "off")
_TRUTHY_TOKENS = ("1", "true", "yes", "on")

# Misconfiguration must be loud, but this is read once per request — warn once.
_warned_knobs: set[str] = set()


def verify_guarantee_enabled() -> bool:
    """Whether /v1/verify pays for the forced critic pass on a non-scoring route.

    Read dynamically (not cached at import) so an operator can flip it without a
    rebuild, and so tests can exercise both settings.
    """
    raw = os.environ.get(_GUARANTEE_ENV, "").strip().lower()
    if not raw:
        return True
    if raw in _FALSEY_TOKENS:
        return False
    if raw not in _TRUTHY_TOKENS and _GUARANTEE_ENV not in _warned_knobs:
        _warned_knobs.add(_GUARANTEE_ENV)
        logger.warning(
            "%s=%r is not a recognised boolean — keeping the verification guarantee on",
            _GUARANTEE_ENV, raw,
        )
    return True


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


def _verifier_ran(result: ExoskeletonResult) -> bool:
    """True when a verifier actually scored ``result.answer``.

    Keyed off the artifact, not the route name: the council/agent paths attach the
    TaskSpec their critic judged the answer against, while ``fast``/``thinking``
    return no spec because no verifier runs there — and a request routed ``fast``
    can still be escalated onto the council path by the security gate, so the
    requested route is not a reliable signal. A clarification short-circuits
    before the critic, so it has a spec but no verdict.
    """
    return (
        result.task_spec is not None
        and result.status != RunStatus.NEEDS_CLARIFICATION
    )


def _spec_for_answer(query: str) -> TaskSpec:
    """Minimal TaskSpec so the critic can judge an answer from a non-scoring route.

    ``verify_answer`` contracts on a TaskSpec (it renders ``to_context()`` into the
    judge prompt), and the fast/thinking routes never build one. The request itself
    IS the goal on those routes, so the spec is derived from it rather than faked:
    confidence 1.0 because there is no council uncertainty to report.
    """
    return TaskSpec(
        goal=query[:_JUDGE_GOAL_CHARS],
        success_criteria=list(_ANSWER_CRITERIA),
        confidence=1.0,
    )


def _verify_pass_budget(remaining_s: float) -> float:
    """Wall clock the forced critic pass may use. ``0.0`` means "refuse to start it".

    ``remaining_s`` is what is left of the request's deadline once the main run is
    done (it can be zero or negative — the run is allowed to consume all of it).

    * Budget left to cover the floor → the pass runs entirely INSIDE the deadline.
    * Budget short of the floor → it borrows, but only up to
      ``_VERIFY_PASS_MAX_OVERRUN_S`` past the deadline, so the response time is
      bounded at ``timeout_s + _VERIFY_PASS_MAX_OVERRUN_S`` no matter how the time
      was spent.
    * Overrun allowance already gone → 0.0. Fail closed on the *guarantee* (report
      "nothing verified") rather than on the deadline: a late verdict is useless to
      the caller that set the deadline, and an unscored envelope is honest.
    """
    if remaining_s >= _VERIFY_PASS_MIN_BUDGET_S:
        return remaining_s
    grant = min(_VERIFY_PASS_MIN_BUDGET_S, remaining_s + _VERIFY_PASS_MAX_OVERRUN_S)
    return grant if grant > 0.0 else 0.0


async def _score_unverified(
    cfg: RuntimeConfig, result: ExoskeletonResult, query: str, *, budget_s: float,
) -> tuple[float, bool]:
    """Run the real critic over an answer that no verifier has scored yet.

    Returns ``(score, performed)``. If the critic itself cannot run — no time left
    in the request's budget included — the answer is ``(0.0, False)``, an honest
    "nothing was verified", never an invented score: a consumer gating money on the
    verdict must be able to tell the difference.
    """
    if not (result.answer or "").strip():
        return 0.0, False
    budget = _verify_pass_budget(budget_s)
    if budget <= 0.0:
        logger.warning(
            "metis verify: request budget exhausted (%.1fs past the deadline) — "
            "delivery critic refused, envelope reports verify_performed=false",
            -budget_s,
        )
        return 0.0, False
    try:
        verdict = await asyncio.wait_for(
            verify_answer(cfg, _spec_for_answer(query), result.answer, query),
            timeout=budget,
        )
    except Exception as exc:  # noqa: BLE001 - type only; a provider error can embed secrets
        logger.warning("metis verify: delivery critic unavailable (%s)", type(exc).__name__)
        return 0.0, False
    return float(verdict.score or 0.0), True


def _envelope(
    result: ExoskeletonResult,
    *,
    min_score: float,
    verify_score: float | None = None,
    verify_performed: bool | None = None,
) -> Dict[str, Any]:
    performed = _verifier_ran(result) if verify_performed is None else bool(verify_performed)
    raw = float(result.verify_score or 0.0) if verify_score is None else float(verify_score)
    # The envelope contract is 0.0–1.0, and a consumer gating money on it compares the
    # number against a bar in that range. Bound it at the one place the envelope's score
    # is produced, so no upstream scorer — the pipeline's own verifier or the forced
    # critic pass — can put an off-scale value where a threshold comparison would read
    # it as overwhelming confidence. Deliberately the SAME reader the critic uses: two
    # bounds functions with different opinions about an off-scale number is how one of
    # them ends up being the one a money gate reads.
    score = clamp_score(raw)
    status = result.status.value
    depth = getattr(result, "depth", None)
    meta = result.metadata or {}
    clar: List[str] = list(result.clarifications or [])
    return {
        "answer": result.answer,
        "status": status,
        # `verified` requires an actual verification: without it a caller passing a
        # permissive min_score would read an unscored run as a clean bill of health.
        "verified": performed and status == RunStatus.SUCCESS.value and score >= min_score,
        "verify_score": round(score, 4),
        "verify_performed": performed,
        # The bar `verified` was decided at, echoed back. Two thresholds that must
        # agree are otherwise configured in two places with no cross-check: the hub's
        # Pay-on-Verified escrow sends its AIMARKET_VERIFY_SCORE_THRESHOLD as
        # `min_verify_score` and then re-applies it to the returned numbers, so a
        # verifier judging at a different bar has to be *detectable* rather than
        # silently producing a verdict the operator never asked for.
        "threshold": round(float(min_score), 4),
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
    ensure_verified: bool = False,
) -> Dict[str, Any]:
    """Shared handler: run one stateless Metis pass and build the envelope.

    Never raises for provider/LLM failures — returns an ``error`` envelope so
    callers get a clean, machine-readable result (and no stack trace leaks).

    ``ensure_verified`` is the /v1/verify contract: when the chosen route ran no
    verifier, score the answer with the real critic before answering. It is an
    explicit parameter (not the default) because this handler is shared with
    ``POST /aimarket/invoke``, whose billed cost profile must stay one pass.
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
    started = time.monotonic()
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
            "verify_score": 0.0, "verify_performed": False,
            "threshold": round(float(min_score), 4),
            "route": (mode or cfg.default_route).value,
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
            "verify_performed": False,
            "threshold": round(float(min_score), 4),
            "route": (mode or cfg.default_route).value,
            "depth": None,
            "iterations": 0,
            "clarifications": [],
            "usage": {},
            "trace_id": None,
            "error": type(exc).__name__,
        }
    score, performed = await _guarantee_verification(
        cfg, result, query,
        ensure_verified=ensure_verified, elapsed_s=time.monotonic() - started,
        timeout_s=timeout_s,
    )
    return _envelope(result, min_score=min_score, verify_score=score, verify_performed=performed)


async def _guarantee_verification(
    cfg: RuntimeConfig,
    result: ExoskeletonResult,
    query: str,
    *,
    ensure_verified: bool,
    elapsed_s: float,
    timeout_s: float,
) -> tuple[float | None, bool | None]:
    """Resolve the ``(verify_score, verify_performed)`` the envelope should carry.

    Returns ``(None, None)`` — "use the run's own numbers" — whenever a verifier
    already scored the answer, or the caller did not ask for the guarantee, or the
    operator switched the (billable) guarantee off, or there is nothing to score (a
    failed/clarifying run has no answer to judge).

    Switching the guarantee off does not fake a verdict: the run's own numbers on a
    non-scoring route are ``verify_score`` 0.0 with ``verify_performed`` false, which
    is the truth, and which a money gate reads as "indeterminate", never as a fault.
    """
    if not ensure_verified or not verify_guarantee_enabled():
        return None, None
    if _verifier_ran(result) or result.status != RunStatus.SUCCESS:
        return None, None
    return await _score_unverified(
        cfg, result, query, budget_s=timeout_s - elapsed_s,
    )


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
        api_key=_api_key, ensure_verified=True,
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

        started = time.monotonic()
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
            # Same /v1/verify guarantee as the non-streamed endpoint: the done frame
            # must never carry an unscored run as if it were a verdict. The critic
            # runs outside the pipeline sink, so the streamed event trace is unchanged.
            score, performed = await _guarantee_verification(
                cfg, result, query, ensure_verified=True,
                elapsed_s=time.monotonic() - started, timeout_s=timeout_s,
            )
            yield _sse("done", _envelope(
                result, min_score=min_score, verify_score=score, verify_performed=performed,
            ))
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

    Deliberately does NOT request the /v1/verify verification guarantee: this is a
    billed capability invoke, and silently adding a second LLM call would change
    the cost the hub priced. The envelope still reports ``verify_performed``
    truthfully, so the caller knows whether the score means anything.
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
