"""Pipeline lifecycle events for observability."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

from metis.observability.logging.tracer import get_trace_id, init_logging

_logger = logging.getLogger("metis.pipeline")

# Optional live event sink — an ambient callback that receives every emitted
# pipeline event as a plain dict, in addition to the log line. It rides a
# ``ContextVar`` (exactly like ``_current_meter`` / ``_trace_id``) so it
# propagates into ``asyncio.gather`` children of the run that installed it, and
# never leaks across concurrent requests. Default ``None`` → pure logging, so a
# standalone Metis is completely unaffected (see run()'s ``on_event`` param).
_event_sink: ContextVar[Optional[Callable[[Dict[str, Any]], None]]] = ContextVar(
    "pipeline_event_sink", default=None
)


def set_event_sink(fn: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Install (or clear, with ``None``) the ambient pipeline-event sink."""
    _event_sink.set(fn)


def clear_event_sink() -> None:
    _event_sink.set(None)


def get_event_sink() -> Optional[Callable[[Dict[str, Any]], None]]:
    return _event_sink.get()


class PipelineEventKind(str, Enum):
    ROUTE_SELECTED = "route_selected"
    DEPTH_LEVEL = "depth_level"
    PERCEPTION = "perception"
    COUNCIL_STARTED = "council_started"
    TASK_SPEC_CREATED = "task_spec_created"
    CONFIDENCE_GATE = "confidence_gate"
    MOA_LAYER1 = "moa_layer1"
    MOA_LAYER2 = "moa_layer2"
    MOA_LAYER3 = "moa_layer3"
    SELF_CONSISTENCY = "self_consistency"
    VERIFY_STARTED = "verify_started"
    VERIFY_PASS = "verify_pass"
    VERIFY_FAIL = "verify_fail"
    ESCALATION = "escalation"
    AGENT_LOOP = "agent_loop"
    TOOL_CALL = "tool_call"
    MCP_CALL = "mcp_call"
    SEARCH_CALL = "search_call"
    BUDGET_EXCEEDED = "budget_exceeded"
    INJECTION_BLOCKED = "injection_blocked"


@dataclass
class PipelineEvent:
    phase: str
    event: str
    data: Dict[str, Any]
    ts: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": "pipeline",
            "pipeline_event": self.event,
            "phase": self.phase,
            "data": self.data,
            "timestamp": self.ts,
            "trace_id": get_trace_id(),
        }


def emit_pipeline_event(
    phase_or_kind: Union[str, PipelineEventKind],
    event: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> PipelineEvent:
    """Emit a high-level pipeline event. Accepts (kind, data) or (phase, event, data)."""
    init_logging()
    if isinstance(phase_or_kind, PipelineEventKind):
        phase = "pipeline"
        event_name = phase_or_kind.value
        payload = event if isinstance(event, dict) else (data or {})
        if isinstance(event, dict):
            payload = event
    else:
        phase = phase_or_kind
        event_name = event
        payload = data or {}

    pe = PipelineEvent(
        phase=phase,
        event=event_name,
        data=payload,
        ts=datetime.now(timezone.utc).isoformat(),
    )
    record = pe.to_dict()
    sink = _event_sink.get()
    if sink is not None:
        # A live consumer (e.g. the SSE trace endpoint) is listening. Never let a
        # misbehaving sink break cognition — swallow everything it raises.
        try:
            sink(record)
        except Exception:  # noqa: BLE001 - tracing must never break the pipeline
            _logger.warning("pipeline event sink failed", exc_info=True)
    log_record = _logger.makeRecord(
        "metis.pipeline", logging.INFO, "(pipeline)", 0,
        f"pipeline:{event_name}", (), None,
    )
    for key, val in record.items():
        setattr(log_record, key, val)
    _logger.handle(log_record)
    return pe
