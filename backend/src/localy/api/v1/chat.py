"""
OpenAI-compatible v1 API router.

Exposes /v1/chat/completions and /v1/models endpoints.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse

from localy.core.config import get_settings
from localy.core.dependencies import get_model_service, verify_api_key
from localy.inference.types import GenerationConfig
from localy.schemas.openai import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    ChatCompletionResponseChoiceMessage,
    ChatCompletionUsage,
    ModelListResponse,
    ModelObject,
    ChatCompletionStreamResponse,
    ChatCompletionResponseStreamChoice,
    ChatCompletionDelta,
)
from localy.services.model_service import ModelService
from localy.services.chat_service import ChatService

v1_router = APIRouter(prefix="/v1", tags=["OpenAI-compatible"])
StreamEvent = tuple[str, Any]


@v1_router.get("/models", response_model=ModelListResponse, dependencies=[Depends(verify_api_key)])
async def list_models(
    model_service: ModelService = Depends(get_model_service),
) -> ModelListResponse:
    """List all available models in the registry in OpenAI-compatible format."""
    models_list = model_service.list_models()
    data = [ModelObject(id=m["id"]) for m in models_list]
    return ModelListResponse(data=data)


@v1_router.post(
    "/chat/completions",
    response_model=None,
    dependencies=[Depends(verify_api_key)],
)
async def chat_completions(
    request: Request,
    payload: ChatCompletionRequest,
    model_service: ModelService = Depends(get_model_service),
) -> ChatCompletionResponse | StreamingResponse:
    """Create a chat completion response matching OpenAI's schema.

    Supports both standard JSON response and server-sent events (SSE) streaming.
    """
    settings = get_settings()

    # Transparent pooling: if a pooled coordinator is serving this model, forward
    # the request to it (llama-server is OpenAI-compatible). Solo path otherwise.
    if settings.pool_enabled:
        from localy.services.pool_service import get_pool_service

        pool = get_pool_service(settings)
        if pool.is_serving(payload.model):
            return await _proxy_to_pool(pool.serving_url(), payload)

    chat_service = ChatService(settings, model_service)

    # Normalize messages
    messages = [{"role": msg.role, "content": msg.content} for msg in payload.messages]

    # Map request configuration
    config = GenerationConfig(
        temperature=payload.temperature,
        top_p=payload.top_p,
        max_tokens=payload.max_tokens or settings.default_context_length,
        stream=payload.stream,
        stop=payload.stop if isinstance(payload.stop, list) else ([payload.stop] if payload.stop else []),
        seed=payload.seed or -1,
    )

    if not payload.stream:
        response = await chat_service.chat_completion(
            model_id=payload.model,
            messages=messages,
            config=config,
        )

        return ChatCompletionResponse(
            model=payload.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatCompletionResponseChoiceMessage(
                        role="assistant",
                        content=response.text,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
            ),
        )

    # Streaming mode
    async def sse_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        started_at = time.perf_counter()
        first_token_at: float | None = None

        def telemetry(phase: str, tokens: int = 0, tokens_per_second: float = 0.0, final: bool = False) -> str:
            elapsed = max(0.0, time.perf_counter() - started_at)
            remaining_tokens = max(config.max_tokens - tokens, 0)
            eta_seconds = (
                remaining_tokens / tokens_per_second
                if tokens_per_second > 0 and not final
                else 0.0 if final else None
            )
            data = {
                "localy": {
                    "type": "stream_metrics",
                    "phase": phase,
                    "elapsed_seconds": round(elapsed, 3),
                    "generated_tokens": tokens,
                    "requested_max_tokens": config.max_tokens,
                    "remaining_tokens": remaining_tokens,
                    "tokens_per_second": round(tokens_per_second, 3),
                    "eta_seconds": round(eta_seconds, 3) if eta_seconds is not None else None,
                    "time_to_first_token_ms": (
                        round((first_token_at - started_at) * 1000, 1) if first_token_at is not None else None
                    ),
                }
            }
            return f"data: {json.dumps(data)}\n\n"

        async def produce() -> None:
            try:
                stream = chat_service.chat_completion_stream(
                    model_id=payload.model,
                    messages=messages,
                    config=config,
                )

                async for chunk in stream:
                    await queue.put(("chunk", chunk))
            except Exception as e:  # noqa: BLE001 - surfaced to SSE client
                await queue.put(("error", e))
            finally:
                await queue.put(("producer_done", None))

        producer = asyncio.create_task(produce())
        yield telemetry("loading")
        try:
            while True:
                if await request.is_disconnected():
                    producer.cancel()
                    break

                try:
                    event_type, event_data = await asyncio.wait_for(queue.get(), timeout=2.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    yield telemetry("loading" if first_token_at is None else "generating")
                    continue

                if event_type == "producer_done":
                    break
                if event_type == "error":
                    raise event_data

                chunk = event_data
                if chunk.is_final:
                    yield telemetry(
                        "complete",
                        tokens=chunk.tokens_generated,
                        tokens_per_second=chunk.tokens_per_second,
                        final=True,
                    )
                    # Final stop chunk
                    final_payload = ChatCompletionStreamResponse(
                        model=payload.model,
                        choices=[
                            ChatCompletionResponseStreamChoice(
                                index=0,
                                delta=ChatCompletionDelta(),
                                finish_reason="stop",
                            )
                        ],
                    )
                    yield f"data: {json.dumps(final_payload.model_dump())}\n\n"
                    yield "data: [DONE]\n\n"
                    break

                stream_payload = ChatCompletionStreamResponse(
                    model=payload.model,
                    choices=[
                        ChatCompletionResponseStreamChoice(
                            index=0,
                            delta=ChatCompletionDelta(role="assistant", content=chunk.token),
                            finish_reason=None,
                        )
                    ],
                )
                yield f"data: {json.dumps(stream_payload.model_dump())}\n\n"
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                yield telemetry(
                    "generating",
                    tokens=chunk.tokens_generated,
                    tokens_per_second=chunk.tokens_per_second,
                )

        except Exception as e:
            error_data = {"error": {"message": str(e), "type": "invalid_request_error"}}
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if not producer.done():
                producer.cancel()

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _proxy_to_pool(base_url: str, request: ChatCompletionRequest):
    """Forward a chat completion to the pooled llama-server (OpenAI-compatible).

    Handles both streaming (SSE passthrough) and non-streaming responses so the
    caller cannot tell whether the model ran solo or across the pool.
    """
    url = f"{base_url}/v1/chat/completions"
    payload = request.model_dump(exclude_none=True)

    if not request.stream:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = await client.post(url, json=payload)
            try:
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            except Exception:
                # Coordinator returned a non-JSON body (crashed / still starting).
                return JSONResponse(
                    status_code=502,
                    content={
                        "error": {
                            "message": f"Pooled server returned a non-JSON response (HTTP {resp.status_code}). "
                            "It may still be loading or has stopped — check the Device Pool page.",
                            "type": "server_error",
                        }
                    },
                )

    async def sse_passthrough() -> AsyncGenerator[str, None]:
        try:
            timeout = httpx.Timeout(None, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        message = body.decode("utf-8", errors="replace") or f"HTTP {resp.status_code}"
                        err = {"error": {"message": f"pooled server error: {message}", "type": "server_error"}}
                        yield f"data: {json.dumps(err)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    async for raw in resp.aiter_raw():
                        if raw:
                            yield raw.decode("utf-8", errors="replace")
        except Exception as e:  # pragma: no cover - network edge
            err = {"error": {"message": f"pool proxy error: {e}", "type": "server_error"}}
            yield f"data: {json.dumps(err)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_passthrough(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
