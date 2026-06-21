"""
Inference type definitions — request/response models for the inference engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelStatus(str, Enum):
    """Model lifecycle status."""

    UNKNOWN = "unknown"
    NOT_DOWNLOADED = "not_downloaded"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"    # On disk but not loaded
    LOADING = "loading"
    READY = "ready"             # Loaded and ready for inference
    UNLOADING = "unloading"
    ERROR = "error"


@dataclass
class GenerationConfig:
    """Configuration for text generation.

    Maps directly to llama.cpp sampling parameters.
    """

    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    max_tokens: int = 2048
    stop: list[str] = field(default_factory=list)
    seed: int = -1  # -1 = random
    stream: bool = False


@dataclass
class InferenceRequest:
    """A request for text generation."""

    prompt: str
    generation_config: GenerationConfig = field(default_factory=GenerationConfig)
    model_id: str = ""


@dataclass
class InferenceResponse:
    """Response from text generation."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    time_to_first_token_ms: float = 0.0
    total_time_ms: float = 0.0
    model_id: str = ""
    finish_reason: str = "stop"


@dataclass
class StreamChunk:
    """A single chunk from streaming generation."""

    token: str
    is_final: bool = False
    tokens_generated: int = 0
    tokens_per_second: float = 0.0


@dataclass
class LoadedModelInfo:
    """Information about the currently loaded model."""

    model_id: str
    file_path: str
    parameter_count_billions: float
    quantization: str
    context_length: int
    status: ModelStatus
    memory_usage_bytes: int = 0
    tokens_per_second_estimate: float = 0.0
