"""Usage metering."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_current_meter: ContextVar[Optional["UsageMeter"]] = ContextVar("usage_meter", default=None)


def get_current_meter() -> Optional["UsageMeter"]:
    return _current_meter.get()


def set_current_meter(meter: Optional["UsageMeter"]) -> None:
    _current_meter.set(meter)


@dataclass
class UsageEvent:
    event_id: str
    model: str
    provider: str
    node_id: Optional[str]
    role: str
    route: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    mcp_tool: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class UsageReport:
    session_id: str
    route: str
    events: List[UsageEvent] = field(default_factory=list)
    mcp_tool_calls: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    currency: str = "USD"
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "session_id": self.session_id,
            "route": self.route,
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "mcp_tool_calls": self.mcp_tool_calls,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "currency": self.currency,
            "event_count": len(self.events),
        }
        if self.trace_id:
            d["trace_id"] = self.trace_id
        return d


class UsageMeter:
    def __init__(self, session_id: Optional[str] = None, route: str = "unknown", trace_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.route = route
        self.trace_id = trace_id
        self._events: List[UsageEvent] = []
        self._mcp_calls = 0

    def record_llm(
        self,
        *,
        model: str,
        provider: str,
        role: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        node_id: Optional[str] = None,
    ) -> UsageEvent:
        event = UsageEvent(
            event_id=str(uuid.uuid4()),
            model=model,
            provider=provider,
            node_id=node_id,
            role=role,
            route=self.route,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            trace_id=self.trace_id,
        )
        self._events.append(event)
        return event

    def record_mcp_tool(self, tool_name: str, latency_ms: float = 0.0) -> None:
        self._mcp_calls += 1
        self._events.append(
            UsageEvent(
                event_id=str(uuid.uuid4()),
                model="mcp",
                provider="mcp",
                node_id=None,
                role="tool",
                route=self.route,
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                mcp_tool=tool_name,
                trace_id=self.trace_id,
            )
        )

    def build_report(self, *, estimated_cost_usd: float = 0.0, currency: str = "USD") -> UsageReport:
        return UsageReport(
            session_id=self.session_id,
            route=self.route,
            events=list(self._events),
            mcp_tool_calls=self._mcp_calls,
            total_tokens_in=sum(e.tokens_in for e in self._events),
            total_tokens_out=sum(e.tokens_out for e in self._events),
            total_latency_ms=sum(e.latency_ms for e in self._events),
            estimated_cost_usd=estimated_cost_usd,
            currency=currency,
            trace_id=self.trace_id,
        )

    @property
    def events(self) -> List[UsageEvent]:
        return self._events
