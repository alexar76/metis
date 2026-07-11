"""Live cognition trace: the ambient pipeline-event sink + the SSE endpoint.

The sink is what turns Metis's *internal* pipeline events into a *live* stream
the landing cognition panel + reactive star consume. These tests pin:

* the sink rides a ContextVar (set/clear), reaches ``asyncio.gather`` children,
  and is a pure no-op by default (standalone Metis is unaffected);
* a misbehaving sink can never break cognition;
* ``POST /v1/verify/stream`` emits ordered real events then a ``done`` envelope,
  with the right SSE headers, and a fast route streams a *sparse* trace with no
  ``verify`` event (so the panel renders "unverified", never hangs).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from metis.api.app import create_app
from metis.config import ProviderKind, RuntimeConfig
from metis.observability.logging.pipeline_events import (
    PipelineEventKind,
    clear_event_sink,
    emit_pipeline_event,
    get_event_sink,
    set_event_sink,
)


@pytest.fixture(autouse=True)
def _clean_sink():
    clear_event_sink()
    yield
    clear_event_sink()


# ── the sink primitive ────────────────────────────────────────────────────────

def test_sink_toggles_contextvar():
    assert get_event_sink() is None
    fn = lambda rec: None
    set_event_sink(fn)
    assert get_event_sink() is fn
    clear_event_sink()
    assert get_event_sink() is None


def test_emit_pushes_to_sink_and_is_noop_by_default():
    # Default: no sink → emit is a pure log, returns the event, pushes nowhere.
    got: list = []
    ev = emit_pipeline_event(PipelineEventKind.ROUTE_SELECTED, {"route": "fast"})
    assert ev.event == "route_selected"
    assert got == []  # nothing captured — no sink installed

    set_event_sink(got.append)
    emit_pipeline_event(PipelineEventKind.MOA_LAYER1, {"attempt": 1})
    assert len(got) == 1
    assert got[0]["pipeline_event"] == "moa_layer1"
    assert got[0]["data"] == {"attempt": 1}
    assert "timestamp" in got[0]


def test_sink_exception_never_breaks_emit():
    def boom(_rec):
        raise ValueError("sink blew up")

    set_event_sink(boom)
    # Must NOT raise — tracing can never break cognition.
    ev = emit_pipeline_event(PipelineEventKind.VERIFY_PASS, {"score": 0.9})
    assert ev.event == "verify_pass"


def test_sink_reaches_gather_children():
    """Mirrors the SSE endpoint: sink set, then gather children must see it."""
    received: list = []

    async def child(kind):
        emit_pipeline_event(kind, {"k": kind.value})

    async def driver():
        set_event_sink(received.append)
        await asyncio.gather(
            child(PipelineEventKind.COUNCIL_STARTED),
            child(PipelineEventKind.MOA_LAYER1),
        )

    asyncio.run(driver())
    names = {r["pipeline_event"] for r in received}
    assert {"council_started", "moa_layer1"} <= names


# ── the SSE endpoint ──────────────────────────────────────────────────────────

@pytest.fixture
def cfg(tmp_path):
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg))


def _frames(text: str):
    """Parse an SSE body into (event, data|None) tuples."""
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):  # keep-alive comment
            continue
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    data = None
        if ev:
            out.append((ev, data))
    return out


def test_stream_council_emits_ordered_trace_then_done(client):
    r = client.post("/v1/verify/stream", json={"input": "What is 2+2?", "route": "council"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers.get("x-accel-buffering") == "no"

    frames = _frames(r.text)
    events = [e for e, _ in frames]
    # Opens with a synthetic start, closes with a done envelope.
    assert events[0] == "start"
    assert events[-1] == "done"
    # Real pipeline events appear in between.
    assert "route_selected" in events
    assert "depth_level" in events
    assert "council_started" in events
    assert "moa_layer1" in events
    assert any(e in ("verify_pass", "verify_fail") for e in events)
    # The done frame carries the verification envelope.
    done = frames[-1][1]
    assert "verify_score" in done and "usage" in done and "answer" in done
    assert 0.0 <= done["verify_score"] <= 1.0


def test_stream_fast_route_is_sparse_no_verify(client):
    r = client.post("/v1/verify/stream", json={"input": "hello", "route": "fast"})
    assert r.status_code == 200
    events = [e for e, _ in _frames(r.text)]
    assert events[0] == "start" and events[-1] == "done"
    assert "route_selected" in events
    # Fast route never verifies — the panel must render "unverified", not hang.
    assert "verify_pass" not in events and "verify_fail" not in events
    assert "council_started" not in events


def test_stream_validation_errors_before_streaming(client):
    assert client.post("/v1/verify/stream", json={"input": "  "}).status_code == 400
    assert client.post("/v1/verify/stream", json={"input": "x", "route": "nope"}).status_code == 400


def test_stream_leaves_no_sink_installed(client):
    """After a streamed run the ambient sink is cleared (no cross-request leak)."""
    client.post("/v1/verify/stream", json={"input": "hi", "route": "fast"})
    assert get_event_sink() is None


def test_run_without_on_event_is_unaffected(cfg):
    """Independence: a plain run installs no sink and returns normally."""
    from metis.exoskeleton import Metis

    async def go():
        return await Metis(cfg).run("2+2?", route=None)

    result = asyncio.run(go())
    assert result is not None
    assert get_event_sink() is None  # never touched
