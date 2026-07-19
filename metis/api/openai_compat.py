"""OpenAI-compatible chat completions and models endpoints."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from metis.api.auth import verify_api_key
from metis.api.bridge import AVAILABLE_MODELS, OpenAIMetisBridge, model_to_route
from metis.api.schemas import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelInfo,
    ModelsListResponse,
)
from metis.config import RouteMode

router = APIRouter()


def _get_bridge(request: Request) -> OpenAIMetisBridge:
    bridge: Optional[OpenAIMetisBridge] = getattr(request.app.state, "bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Metis not initialized")
    return bridge


def _max_body_bytes() -> int:
    return int(os.environ.get("METIS_MAX_REQUEST_BYTES", "1048576"))


def _check_request_size(body: ChatCompletionRequest) -> None:
    raw = json.dumps(body.model_dump())
    if len(raw.encode("utf-8")) > _max_body_bytes():
        raise HTTPException(status_code=413, detail="Request body too large")


def _openai_response(
    content: str,
    model: str,
    usage: Dict[str, int],
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(
                message={"role": "assistant", "content": content},
            )
        ],
        usage=usage,
    )


async def _stream_sse(
    bridge: OpenAIMetisBridge,
    messages: List[Dict[str, str]],
    model: str,
    forced_route: Optional[RouteMode],
) -> AsyncIterator[str]:
    result = await bridge.process(
        messages,
        model=model,
        forced_route=forced_route,
    )
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    async for chunk in bridge.stream_tokens(result.content):
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(payload)}\n\n"

    final = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


@router.get("/models", response_model=ModelsListResponse)
async def list_models(
    api_key: Optional[str] = Depends(verify_api_key),
) -> ModelsListResponse:
    created = int(time.time())
    return ModelsListResponse(
        data=[ModelInfo(id=name, created=created, owned_by="metis") for name in AVAILABLE_MODELS]
    )


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    api_key: Optional[str] = Depends(verify_api_key),
    bridge: OpenAIMetisBridge = Depends(_get_bridge),
):
    _check_request_size(body)

    if not body.messages:
        raise HTTPException(status_code=400, detail="messages is required")

    messages = [m.model_dump() for m in body.messages]
    forced = model_to_route(body.model)

    if body.stream:
        return StreamingResponse(
            _stream_sse(bridge, messages, body.model, forced),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await bridge.process(
        messages,
        model=body.model,
        forced_route=forced,
    )
    return _openai_response(result.content, body.model, result.usage)
