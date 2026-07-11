"""Feedback and trace API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from metis.api.auth import verify_api_key
from metis.observability.trace_store import TraceStore


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class FeedbackResponse(BaseModel):
    ok: bool
    trace_id: str


def build_observability_router(
    *,
    get_knowledge_store: Callable,
    trace_dir: str,
) -> APIRouter:
    router = APIRouter()

    @router.post("/feedback", response_model=FeedbackResponse)
    async def submit_feedback(
        body: FeedbackRequest,
        _key: Optional[str] = Depends(verify_api_key),
    ) -> FeedbackResponse:
        store = get_knowledge_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Knowledge store disabled")
        store.add_feedback(body.trace_id, body.rating, body.comment)
        return FeedbackResponse(ok=True, trace_id=body.trace_id)

    @router.get("/traces/{trace_id}")
    async def get_trace(
        trace_id: str,
        _key: Optional[str] = Depends(verify_api_key),
    ) -> dict:
        ts = TraceStore(Path(trace_dir))
        rec = ts.get(trace_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Trace not found")
        return rec

    return router
