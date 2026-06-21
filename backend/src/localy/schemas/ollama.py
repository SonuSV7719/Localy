"""
Ollama-compatible request and response Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


class OllamaMessage(BaseModel):
    """Message object for Ollama API chat."""

    role: str
    content: str
    images: list[str] | None = None


class ChatRequest(BaseModel):
    """Ollama /api/chat request."""

    model: str
    messages: list[OllamaMessage]
    stream: bool = True
    options: dict[str, Any] | None = None
    keep_alive: str | int | None = None


class ChatResponse(BaseModel):
    """Ollama /api/chat response chunk or final object."""

    model: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    message: OllamaMessage | None = None
    done: bool
    done_reason: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None


class GenerateRequest(BaseModel):
    """Ollama /api/generate request."""

    model: str
    prompt: str
    system: str | None = None
    template: str | None = None
    context: list[int] | None = None
    stream: bool = True
    raw: bool = False
    images: list[str] | None = None
    options: dict[str, Any] | None = None
    keep_alive: str | int | None = None


class GenerateResponse(BaseModel):
    """Ollama /api/generate response chunk or final object."""

    model: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    response: str
    done: bool
    context: list[int] | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None


class PullRequest(BaseModel):
    """Ollama /api/pull request."""

    name: str
    insecure: bool = False
    stream: bool = True


class PullResponse(BaseModel):
    """Ollama /api/pull response streaming update."""

    status: str
    digest: str | None = None
    total: int | None = None
    completed: int | None = None


class OllamaModelDetails(BaseModel):
    """Ollama model details schema."""

    parent_model: str = ""
    format: str = "gguf"
    family: str = "llama"
    families: list[str] = ["llama"]
    parameter_size: str = ""
    quantization_level: str = ""


class OllamaModel(BaseModel):
    """Ollama model metadata schema."""

    name: str
    model: str
    modified_at: str
    size: int
    digest: str = ""
    details: OllamaModelDetails


class TagsResponse(BaseModel):
    """Ollama /api/tags response model."""

    models: list[OllamaModel]
