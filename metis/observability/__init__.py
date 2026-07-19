"""Production observability: structured logging, tracing, retries, failure detection."""

from metis.observability.config import ObservabilityConfig, ReliabilityConfig
from metis.observability.logging.pipeline_events import (
    PipelineEventKind,
    clear_event_sink,
    emit_pipeline_event,
    get_event_sink,
    set_event_sink,
)
from metis.observability.logging.tracer import (
    TraceContext,
    clear_trace,
    get_trace_id,
    init_logging,
    set_trace_id,
    start_trace,
)
from metis.observability.reliability.detector import FailureKind, FailureRecord, classify_failure
from metis.observability.reliability.retry import RetryPolicy, with_retry
from metis.observability.trace_store import TraceStore

__all__ = [
    "ObservabilityConfig",
    "ReliabilityConfig",
    "TraceContext",
    "TraceStore",
    "FailureKind",
    "FailureRecord",
    "PipelineEventKind",
    "RetryPolicy",
    "classify_failure",
    "clear_event_sink",
    "clear_trace",
    "emit_pipeline_event",
    "get_event_sink",
    "get_trace_id",
    "init_logging",
    "set_event_sink",
    "set_trace_id",
    "start_trace",
    "with_retry",
]
