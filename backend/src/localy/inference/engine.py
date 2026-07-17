"""
Localy Inference Engine.

Wraps llama-cpp-python to manage the loading, unloading, and execution of GGUF models.
Implements async generators for streaming tokens, OOM resilience, and thread-pool execution
to keep the FastAPI event loop responsive.
"""

from __future__ import annotations

import asyncio
import gc
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator

from localy.core.exceptions import (
    InferenceError,
    ModelLoadError,
    NoModelLoadedError,
)
from localy.core.logging import get_logger
from localy.inference.types import (
    GenerationConfig,
    InferenceRequest,
    InferenceResponse,
    LoadedModelInfo,
    ModelStatus,
    StreamChunk,
)

if TYPE_CHECKING:
    from localy.core.config import Settings
    from localy.tuning.optimizer import InferenceConfig

logger = get_logger(__name__)

# Global singleton engine instance
_engine_instance: InferenceEngine | None = None


def find_mmproj(model_path: Path) -> Path | None:
    """Locate a multimodal projector (mmproj) GGUF for a vision model.

    llama.cpp vision models ship a companion `*mmproj*.gguf`. We look in the
    model file's own directory. Returns None for text-only models.
    """
    try:
        for f in model_path.parent.glob("*.gguf"):
            if "mmproj" in f.name.lower() or "mproj" in f.name.lower():
                return f
    except OSError:
        pass
    return None


def looks_like_vision_model(model_id: str) -> bool:
    """Heuristic: does this model id/name indicate a vision model? Used to avoid
    mis-detecting a stray mmproj in the shared models dir as belonging to a
    text-only model."""
    name = model_id.lower()
    return any(k in name for k in ("vl", "vision", "llava", "minicpm-v", "moondream", "multimodal", "nanollava"))


def build_vision_chat_handler(model_id: str, mmproj_path: Path) -> Any | None:
    """Construct the right llama-cpp-python vision chat handler for a model.

    Selection is by model-id family; falls back to the LLaVA-1.5 handler, which
    covers the most common projector format. Returns None on any failure so the
    caller can load the model as text-only rather than crash.
    """
    name = model_id.lower()
    try:
        from llama_cpp import llama_chat_format as fmt

        clip = str(mmproj_path)
        if "qwen2.5-vl" in name or "qwen2-vl" in name or "qwenvl" in name or "qwen-vl" in name:
            return fmt.Qwen25VLChatHandler(clip_model_path=clip, verbose=False)
        if "minicpm" in name:
            return fmt.MiniCPMv26ChatHandler(clip_model_path=clip, verbose=False)
        if "moondream" in name:
            return fmt.MoondreamChatHandler(clip_model_path=clip, verbose=False)
        if "nanollava" in name or "nano-llava" in name:
            return fmt.NanoLlavaChatHandler(clip_model_path=clip, verbose=False)
        if "llava-1.6" in name or "llava16" in name or "llava-v1.6" in name:
            return fmt.Llava16ChatHandler(clip_model_path=clip, verbose=False)
        # Sensible default for other/unknown vision models.
        return fmt.Llava15ChatHandler(clip_model_path=clip, verbose=False)
    except Exception as e:  # noqa: BLE001 - never let vision setup break loading
        logger.warning("vision_handler_init_failed", model_id=model_id, error=str(e))
        return None


class InferenceEngine:
    """Wrapper around llama_cpp.Llama to manage model lifecycle and inference."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm: Any | None = None
        self._loaded_model_id: str | None = None
        self._loaded_model_path: Path | None = None
        self._config: InferenceConfig | None = None
        self._is_vision = False
        self._lock = asyncio.Lock()

    @property
    def is_vision(self) -> bool:
        """True if the loaded model was loaded with a vision chat handler."""
        return self._is_vision

    @property
    def loaded_model_id(self) -> str | None:
        """Get the ID of the currently loaded model."""
        return self._loaded_model_id

    @property
    def is_model_loaded(self) -> bool:
        """Check if any model is currently loaded."""
        return self._llm is not None

    async def get_loaded_model_info(self) -> LoadedModelInfo | None:
        """Get detailed info about the currently loaded model."""
        async with self._lock:
            if self._llm is None or self._loaded_model_id is None or self._loaded_model_path is None or self._config is None:
                return None

            return LoadedModelInfo(
                model_id=self._loaded_model_id,
                file_path=str(self._loaded_model_path),
                parameter_count_billions=self._estimate_params_from_path(self._loaded_model_path),
                quantization=self._config.tuning_profile,
                context_length=self._config.n_ctx,
                status=ModelStatus.READY,
                memory_usage_bytes=self._loaded_model_path.stat().st_size,  # Rough estimate
            )

    def _estimate_params_from_path(self, path: Path) -> float:
        """Estimate model parameters from filename as fallback."""
        name = path.name.lower()
        import re
        match = re.search(r"(\d+(\.\d+)?)[bb]", name)
        if match:
            return float(match.group(1))
        return 0.0

    async def load_model(
        self,
        model_id: str,
        model_path: Path,
        config: InferenceConfig,
    ) -> None:
        """Load a model into memory with the specified inference config.

        If a different model is loaded, it is automatically unloaded first.
        If the same model is already loaded with the same config, does nothing.
        """
        async with self._lock:
            if self._loaded_model_id == model_id and self._config == config and self._llm is not None:
                logger.info("model_already_loaded_with_matching_config", model_id=model_id)
                return

            if self._llm is not None:
                logger.info("unloading_previous_model", previous_model_id=self._loaded_model_id)
                self._unload_model_unlocked()

            logger.info(
                "loading_model",
                model_id=model_id,
                path=str(model_path),
                ctx=config.n_ctx,
                threads=config.n_threads,
            )

            try:
                # Import here to avoid loading native libs on startup
                from llama_cpp import Llama

                # Detect a vision projector; if present, load with the matching
                # multimodal chat handler so images are supported. Falls back to
                # a plain text load if anything about vision setup fails.
                mmproj = find_mmproj(model_path) if looks_like_vision_model(model_id) else None
                vision_handler = build_vision_chat_handler(model_id, mmproj) if mmproj else None
                self._is_vision = vision_handler is not None
                if self._is_vision:
                    logger.info("loading_vision_model", model_id=model_id, mmproj=str(mmproj))

                # Execute blockingly in executor thread to keep async loop responsive
                def _init_llama() -> Llama:
                    kwargs: dict[str, Any] = dict(
                        model_path=str(model_path),
                        n_ctx=config.n_ctx,
                        n_threads=config.n_threads,
                        n_threads_batch=config.n_threads_batch,
                        n_batch=config.n_batch,
                        n_gpu_layers=config.n_gpu_layers,
                        use_mmap=config.use_mmap,
                        use_mlock=config.use_mlock,
                        flash_attn=config.flash_attn,
                        verbose=False,
                    )
                    if vision_handler is not None:
                        kwargs["chat_handler"] = vision_handler
                    return Llama(**kwargs)

                self._llm = await asyncio.to_thread(_init_llama)
                self._loaded_model_id = model_id
                self._loaded_model_path = model_path
                self._config = config
                logger.info("model_loaded_successfully", model_id=model_id)

            except Exception as e:
                logger.error("failed_to_load_model", model_id=model_id, error=str(e))
                self._unload_model_unlocked()
                raise ModelLoadError(
                    f"Failed to load model '{model_id}' into inference engine: {e}",
                    details={"model_id": model_id, "path": str(model_path), "error": str(e)},
                ) from e

    async def unload_model(self) -> None:
        """Unload the currently loaded model and free memory."""
        async with self._lock:
            self._unload_model_unlocked()

    def _unload_model_unlocked(self) -> None:
        """Unload model (internal helper, must hold lock or call when safe)."""
        if self._llm is not None:
            # Explicit delete and garbage collection to release memory immediately
            del self._llm
            self._llm = None
            self._loaded_model_id = None
            self._loaded_model_path = None
            self._config = None
            self._is_vision = False
            # Force GC and free llama.cpp memory pool
            gc.collect()
            logger.info("model_unloaded")

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Generate response for a non-streaming request."""
        # Acquire lock to ensure thread safety
        async with self._lock:
            if self._llm is None:
                raise NoModelLoadedError("No model is currently loaded. Load a model first.")

            logger.info("running_inference", prompt_len=len(request.prompt))

            start_time = time.perf_counter()
            try:
                # Wrap execution in thread executor to prevent blocking FastAPI
                def _run_inference() -> dict[str, Any]:
                    assert self._llm is not None
                    return self._llm.create_completion(
                        prompt=request.prompt,
                        max_tokens=request.generation_config.max_tokens,
                        temperature=request.generation_config.temperature,
                        top_p=request.generation_config.top_p,
                        top_k=request.generation_config.top_k,
                        repeat_penalty=request.generation_config.repeat_penalty,
                        stop=request.generation_config.stop,
                        seed=request.generation_config.seed,
                        stream=False,
                    )

                result = await asyncio.to_thread(_run_inference)
                elapsed = time.perf_counter() - start_time

                text = result["choices"][0]["text"]
                usage = result.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

                tps = completion_tokens / elapsed if elapsed > 0 else 0.0

                return InferenceResponse(
                    text=text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    tokens_per_second=tps,
                    total_time_ms=elapsed * 1000,
                    model_id=self._loaded_model_id or "",
                    finish_reason=result["choices"][0].get("finish_reason", "stop"),
                )

            except Exception as e:
                logger.error("inference_failed", error=str(e))
                raise InferenceError(f"Error during inference: {e}") from e

    async def generate_stream(self, request: InferenceRequest) -> AsyncGenerator[StreamChunk, None]:
        """Generate streaming response as an async generator."""
        if self._llm is None:
            raise NoModelLoadedError("No model is currently loaded. Load a model first.")

        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _sync_stream_worker() -> None:
            try:
                assert self._llm is not None
                response = self._llm.create_completion(
                    prompt=request.prompt,
                    max_tokens=request.generation_config.max_tokens,
                    temperature=request.generation_config.temperature,
                    top_p=request.generation_config.top_p,
                    top_k=request.generation_config.top_k,
                    repeat_penalty=request.generation_config.repeat_penalty,
                    stop=request.generation_config.stop,
                    seed=request.generation_config.seed,
                    stream=True,
                )
                for chunk in response:
                    text = chunk["choices"][0].get("text", "")
                    loop.call_soon_threadsafe(queue.put_nowait, ("token", text))

                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", e))

        # Start background thread for inference streaming
        worker_task = asyncio.to_thread(_sync_stream_worker)
        asyncio.create_task(worker_task)

        start_time = time.perf_counter()
        tokens_generated = 0

        while True:
            msg_type, data = await queue.get()
            if msg_type == "done":
                yield StreamChunk(token="", is_final=True, tokens_generated=tokens_generated)
                break
            elif msg_type == "error":
                logger.error("stream_inference_failed", error=str(data))
                raise InferenceError(f"Error during stream generation: {data}") from data
            elif msg_type == "token":
                if data:
                    tokens_generated += 1
                    elapsed = time.perf_counter() - start_time
                    tps = tokens_generated / elapsed if elapsed > 0 else 0.0
                    yield StreamChunk(
                        token=data,
                        is_final=False,
                        tokens_generated=tokens_generated,
                        tokens_per_second=tps,
                    )
            queue.task_done()

    def _normalize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pass multimodal content through for vision models; flatten it to text
        for text-only models so a list-content message never breaks them."""
        if self._is_vision:
            return messages

        def flatten(content: Any) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                out: list[str] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        out.append(str(part.get("text", "")))
                    elif part.get("type") == "image_url":
                        out.append("[image omitted — this model does not support vision]")
                return "\n".join(out)
            return str(content)

        return [{**m, "content": flatten(m.get("content"))} for m in messages]

    async def generate_chat(
        self,
        messages: list[dict[str, Any]],
        generation_config: GenerationConfig,
    ) -> InferenceResponse:
        """Generate chat response for a non-streaming chat request."""
        async with self._lock:
            if self._llm is None:
                raise NoModelLoadedError("No model is currently loaded. Load a model first.")

            messages = self._normalize_messages(messages)
            logger.info("running_chat_inference", message_count=len(messages))

            start_time = time.perf_counter()
            try:
                def _run_chat_inference() -> dict[str, Any]:
                    assert self._llm is not None
                    return self._llm.create_chat_completion(
                        messages=messages,  # type: ignore[arg-type]
                        max_tokens=generation_config.max_tokens,
                        temperature=generation_config.temperature,
                        top_p=generation_config.top_p,
                        top_k=generation_config.top_k,
                        repeat_penalty=generation_config.repeat_penalty,
                        stop=generation_config.stop,
                        seed=generation_config.seed,
                        stream=False,
                    )

                result = await asyncio.to_thread(_run_chat_inference)
                elapsed = time.perf_counter() - start_time

                text = result["choices"][0]["message"]["content"] or ""
                usage = result.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

                tps = completion_tokens / elapsed if elapsed > 0 else 0.0

                return InferenceResponse(
                    text=text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    tokens_per_second=tps,
                    total_time_ms=elapsed * 1000,
                    model_id=self._loaded_model_id or "",
                    finish_reason=result["choices"][0].get("finish_reason", "stop"),
                )

            except Exception as e:
                logger.error("chat_inference_failed", error=str(e))
                raise InferenceError(f"Error during chat inference: {e}") from e

    async def generate_chat_stream(
        self,
        messages: list[dict[str, Any]],
        generation_config: GenerationConfig,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Generate streaming chat response as an async generator."""
        if self._llm is None:
            raise NoModelLoadedError("No model is currently loaded. Load a model first.")

        messages = self._normalize_messages(messages)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _sync_chat_stream_worker() -> None:
            try:
                assert self._llm is not None
                response = self._llm.create_chat_completion(
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=generation_config.max_tokens,
                    temperature=generation_config.temperature,
                    top_p=generation_config.top_p,
                    top_k=generation_config.top_k,
                    repeat_penalty=generation_config.repeat_penalty,
                    stop=generation_config.stop,
                    seed=generation_config.seed,
                    stream=True,
                )
                for chunk in response:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        loop.call_soon_threadsafe(queue.put_nowait, ("token", content))

                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", e))

        # Start background thread for inference streaming
        worker_task = asyncio.to_thread(_sync_chat_stream_worker)
        asyncio.create_task(worker_task)

        start_time = time.perf_counter()
        tokens_generated = 0

        while True:
            msg_type, data = await queue.get()
            if msg_type == "done":
                yield StreamChunk(token="", is_final=True, tokens_generated=tokens_generated)
                break
            elif msg_type == "error":
                logger.error("stream_chat_inference_failed", error=str(data))
                raise InferenceError(f"Error during streaming chat inference: {data}") from data
            elif msg_type == "token":
                if data:
                    tokens_generated += 1
                    elapsed = time.perf_counter() - start_time
                    tps = tokens_generated / elapsed if elapsed > 0 else 0.0
                    yield StreamChunk(
                        token=data,
                        is_final=False,
                        tokens_generated=tokens_generated,
                        tokens_per_second=tps,
                    )
            queue.task_done()


def get_engine(settings: Settings) -> InferenceEngine:
    """Get the singleton InferenceEngine instance.

    Args:
        settings: Application Settings.

    Returns:
        The InferenceEngine singleton.
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = InferenceEngine(settings)
    return _engine_instance
