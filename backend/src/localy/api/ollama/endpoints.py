"""
Ollama-compatible REST API endpoints.

Implements /api/chat, /api/generate, /api/tags, /api/pull, /api/show, and /api/delete.
Matches Ollama API behavior exactly, including line-delimited JSON streaming.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from localy.core.config import get_settings
from localy.core.dependencies import get_model_service, verify_api_key
from localy.inference.types import GenerationConfig, InferenceRequest
from localy.schemas.ollama import (
    ChatRequest,
    ChatResponse,
    GenerateRequest,
    GenerateResponse,
    PullRequest,
    PullResponse,
    TagsResponse,
    OllamaModel,
    OllamaModelDetails,
    OllamaMessage,
)
from localy.services.model_service import ModelService
from localy.services.chat_service import ChatService

ollama_router = APIRouter(prefix="/api", tags=["Ollama-compatible"])


@ollama_router.get("/tags", response_model=TagsResponse, dependencies=[Depends(verify_api_key)])
async def list_tags(
    model_service: ModelService = Depends(get_model_service),
) -> TagsResponse:
    """Get list of downloaded local models in Ollama format."""
    models_list = model_service.list_models()
    ollama_models = []

    for m in models_list:
        for v in m["variants"]:
            if v["is_downloaded"]:
                # Parse parameter size representation
                p_size = f"{m['parameter_count_billions']:.1f}B"

                # Created/modified time representation
                modified_time = datetime.now(timezone.utc).isoformat() + "Z"

                ollama_models.append(
                    OllamaModel(
                        name=f"{m['name']}:{v['quantization'].lower()}",
                        model=f"{m['name']}:{v['quantization'].lower()}",
                        modified_at=modified_time,
                        size=v["file_size_bytes"],
                        digest=v["quantization"],
                        details=OllamaModelDetails(
                            parent_model="",
                            format="gguf",
                            family=m["family"],
                            families=[m["family"]],
                            parameter_size=p_size,
                            quantization_level=v["quantization"],
                        ),
                    )
                )

    return TagsResponse(models=ollama_models)


@ollama_router.post("/chat", response_model=None, dependencies=[Depends(verify_api_key)])
async def ollama_chat(
    request: ChatRequest,
    model_service: ModelService = Depends(get_model_service),
) -> ChatResponse | StreamingResponse:
    """Ollama-compatible chat completion.

    Outputs line-delimited JSON for streaming.
    """
    settings = get_settings()
    chat_service = ChatService(settings, model_service)

    # Normalize messages
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    # Map options to generation config
    options = request.options or {}
    config = GenerationConfig(
        temperature=options.get("temperature", 0.7),
        top_p=options.get("top_p", 0.9),
        max_tokens=options.get("num_predict", settings.default_context_length),
        stream=request.stream,
        stop=options.get("stop", []),
        seed=options.get("seed", -1),
    )

    if not request.stream:
        response = await chat_service.chat_completion(
            model_id=request.model,
            messages=messages,
            config=config,
        )

        return ChatResponse(
            model=request.model,
            message=OllamaMessage(role="assistant", content=response.text),
            done=True,
            done_reason="stop",
            total_duration=int(response.total_time_ms * 1_000_000),  # Nanoseconds
            eval_count=response.completion_tokens,
            prompt_eval_count=response.prompt_tokens,
        )

    # Streaming mode (line-delimited JSON)
    async def stream_generator() -> AsyncGenerator[str, None]:
        try:
            stream = chat_service.chat_completion_stream(
                model_id=request.model,
                messages=messages,
                config=config,
            )

            async for chunk in stream:
                if chunk.is_final:
                    final_payload = ChatResponse(
                        model=request.model,
                        done=True,
                        done_reason="stop",
                    )
                    yield json.dumps(final_payload.model_dump(exclude_none=True)) + "\n"
                    break

                payload = ChatResponse(
                    model=request.model,
                    message=OllamaMessage(role="assistant", content=chunk.token),
                    done=False,
                )
                yield json.dumps(payload.model_dump(exclude_none=True)) + "\n"

        except Exception as e:
            error_payload = ChatResponse(
                model=request.model,
                done=True,
                done_reason=f"error: {e}",
            )
            yield json.dumps(error_payload.model_dump(exclude_none=True)) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")


@ollama_router.post("/generate", response_model=None, dependencies=[Depends(verify_api_key)])
async def ollama_generate(
    request: GenerateRequest,
    model_service: ModelService = Depends(get_model_service),
) -> GenerateResponse | StreamingResponse:
    """Ollama-compatible raw generation (completion)."""
    settings = get_settings()

    # Resolve active model loading
    from localy.inference.engine import get_engine
    engine = get_engine(settings)

    # Ensure requested model is loaded
    active_model = await engine.get_loaded_model_info()
    if active_model is None or active_model.model_id != request.model:
        await model_service.load_model(request.model)

    options = request.options or {}
    config = GenerationConfig(
        temperature=options.get("temperature", 0.7),
        top_p=options.get("top_p", 0.9),
        max_tokens=options.get("num_predict", settings.default_context_length),
        stream=request.stream,
        stop=options.get("stop", []),
        seed=options.get("seed", -1),
    )

    inf_req = InferenceRequest(prompt=request.prompt, generation_config=config)

    if not request.stream:
        response = await engine.generate(inf_req)
        return GenerateResponse(
            model=request.model,
            response=response.text,
            done=True,
            total_duration=int(response.total_time_ms * 1_000_000),
            eval_count=response.completion_tokens,
            prompt_eval_count=response.prompt_tokens,
        )

    # Streaming mode
    async def generate_stream_generator() -> AsyncGenerator[str, None]:
        try:
            async for chunk in engine.generate_stream(inf_req):
                if chunk.is_final:
                    final_payload = GenerateResponse(
                        model=request.model,
                        response="",
                        done=True,
                    )
                    yield json.dumps(final_payload.model_dump(exclude_none=True)) + "\n"
                    break

                payload = GenerateResponse(
                    model=request.model,
                    response=chunk.token,
                    done=False,
                )
                yield json.dumps(payload.model_dump(exclude_none=True)) + "\n"

        except Exception as e:
            error_payload = GenerateResponse(
                model=request.model,
                response=f"error: {e}",
                done=True,
            )
            yield json.dumps(error_payload.model_dump(exclude_none=True)) + "\n"

    return StreamingResponse(generate_stream_generator(), media_type="application/x-ndjson")


@ollama_router.post("/pull", dependencies=[Depends(verify_api_key)])
async def pull_model_endpoint(
    request: PullRequest,
    model_service: ModelService = Depends(get_model_service),
) -> StreamingResponse:
    """Download a model with progress reports matching Ollama's format."""

    async def progress_stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[tuple[int, int, float]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def progress_cb(completed: int, total: int, speed: float) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (completed, total, speed))

        async def download_worker() -> None:
            try:
                await model_service.pull_model(
                    model_spec=request.name,
                    progress_callback=progress_cb,
                    force=False,
                )
                loop.call_soon_threadsafe(queue.put_nowait, (-1, -1, 0.0))  # Sentinel for completion
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, (-2, -2, 0.0))  # Sentinel for error

        # Start download in background
        import asyncio
        asyncio.create_task(download_worker())

        yield json.dumps({"status": "pulling manifest"}) + "\n"

        while True:
            completed, total, speed = await queue.get()
            if completed == -1:
                yield json.dumps({"status": "success"}) + "\n"
                break
            elif completed == -2:
                yield json.dumps({"status": "error downloading model"}) + "\n"
                break
            else:
                pct = int(completed / total * 100) if total > 0 else 0
                yield (
                    json.dumps(
                        {
                            "status": f"downloading {pct}%",
                            "digest": request.name,
                            "total": total,
                            "completed": completed,
                        }
                    )
                    + "\n"
                )
            queue.task_done()

    return StreamingResponse(progress_stream(), media_type="application/x-ndjson")


@ollama_router.post("/show", dependencies=[Depends(verify_api_key)])
async def show_model(
    payload: dict[str, str],
    model_service: ModelService = Depends(get_model_service),
) -> dict[str, Any]:
    """Show details of a model."""
    name = payload.get("name", "")
    models_list = model_service.list_models()

    for m in models_list:
        if m["id"] == name or m["name"] == name:
            return {
                "license": m["license"],
                "modelfile": f"FROM {m['name']}\nPARAMETER temperature 0.7",
                "parameters": f"parameter_size {m['parameter_count_billions']:.1f}B",
                "details": {
                    "format": "gguf",
                    "family": m["family"],
                    "parameter_size": f"{m['parameter_count_billions']:.1f}B",
                },
            }

    return {"error": "model not found"}


@ollama_router.delete("/delete", dependencies=[Depends(verify_api_key)])
async def delete_model(
    payload: dict[str, str],
    model_service: ModelService = Depends(get_model_service),
) -> dict[str, str]:
    """Delete a local model."""
    name = payload.get("name", "")
    try:
        model_service.delete_model(name)
        return {"status": "success"}
    except Exception as e:
        return {"status": f"error: {e}"}
