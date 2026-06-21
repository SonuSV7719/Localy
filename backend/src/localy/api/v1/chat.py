"""
OpenAI-compatible v1 API router.

Exposes /v1/chat/completions and /v1/models endpoints.
"""

from __future__ import annotations

import json
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

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
    request: ChatCompletionRequest,
    model_service: ModelService = Depends(get_model_service),
) -> ChatCompletionResponse | StreamingResponse:
    """Create a chat completion response matching OpenAI's schema.

    Supports both standard JSON response and server-sent events (SSE) streaming.
    """
    settings = get_settings()
    chat_service = ChatService(settings, model_service)

    # Normalize messages
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    # Map request configuration
    config = GenerationConfig(
        temperature=request.temperature,
        top_p=request.top_p,
        max_tokens=request.max_tokens or settings.default_context_length,
        stream=request.stream,
        stop=request.stop if isinstance(request.stop, list) else ([request.stop] if request.stop else []),
        seed=request.seed or -1,
    )

    if not request.stream:
        response = await chat_service.chat_completion(
            model_id=request.model,
            messages=messages,
            config=config,
        )

        return ChatCompletionResponse(
            model=request.model,
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
        try:
            stream = chat_service.chat_completion_stream(
                model_id=request.model,
                messages=messages,
                config=config,
            )

            async for chunk in stream:
                if chunk.is_final:
                    # Final stop chunk
                    final_payload = ChatCompletionStreamResponse(
                        model=request.model,
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

                payload = ChatCompletionStreamResponse(
                    model=request.model,
                    choices=[
                        ChatCompletionResponseStreamChoice(
                            index=0,
                            delta=ChatCompletionDelta(role="assistant", content=chunk.token),
                            finish_reason=None,
                        )
                    ],
                )
                yield f"data: {json.dumps(payload.model_dump())}\n\n"

        except Exception as e:
            error_data = {"error": {"message": str(e), "type": "invalid_request_error"}}
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")
