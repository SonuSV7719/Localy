"""
Localy Chat Service.

Orchestrates conversation completion requests, automated model switching/loading,
and formats requests for the inference engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator, Any

from localy.core.config import Settings
from localy.core.exceptions import NoModelLoadedError
from localy.core.logging import get_logger
from localy.inference.engine import get_engine
from localy.inference.types import GenerationConfig, InferenceResponse, StreamChunk

if TYPE_CHECKING:
    from localy.services.model_service import ModelService

logger = get_logger(__name__)


class ChatService:
    """High-level service coordinating chat completion logic and automatic model loading."""

    def __init__(self, settings: Settings, model_service: ModelService) -> None:
        self._settings = settings
        self._model_service = model_service

    async def chat_completion(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        config: GenerationConfig,
    ) -> InferenceResponse:
        """Execute a non-streaming chat completion request.

        Automatically loads the model if not loaded or if a model switch is requested.
        """
        engine = get_engine(self._settings)

        # Check if the requested model is already loaded
        active_model = await engine.get_loaded_model_info()
        if active_model is None or active_model.model_id != model_id:
            logger.info("auto_loading_model_for_chat", requested_model=model_id)
            await self._model_service.load_model(model_id)

        return await engine.generate_chat(messages, config)

    async def chat_completion_stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        config: GenerationConfig,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Execute a streaming chat completion request.

        Automatically loads the model if not loaded or if a model switch is requested.
        """
        engine = get_engine(self._settings)

        # Check if the requested model is already loaded
        active_model = await engine.get_loaded_model_info()
        if active_model is None or active_model.model_id != model_id:
            logger.info("auto_loading_model_for_chat_stream", requested_model=model_id)
            await self._model_service.load_model(model_id)

        async for chunk in engine.generate_chat_stream(messages, config):
            yield chunk
