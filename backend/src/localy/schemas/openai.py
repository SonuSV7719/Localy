"""
OpenAI-compatible request and response Pydantic schemas.
"""

from __future__ import annotations

import time
from typing import Any, Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A message in the chat conversation history."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI chat completions request payload."""

    model: str
    messages: list[ChatMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = Field(default=False)
    stop: str | list[str] | None = Field(default=None)
    seed: int | None = Field(default=None)


class ChatCompletionUsage(BaseModel):
    """Token usage info."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponseChoiceMessage(BaseModel):
    """Message object inside response choice."""

    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionResponseChoice(BaseModel):
    """A single completion choice."""

    index: int = 0
    message: ChatCompletionResponseChoiceMessage
    finish_reason: Literal["stop", "length", "content_filter"] = "stop"


class ChatCompletionResponse(BaseModel):
    """OpenAI chat completion response model."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{int(time.time())}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatCompletionResponseChoice]
    usage: ChatCompletionUsage


class ChatCompletionDelta(BaseModel):
    """Delta update content for streaming chunks."""

    role: Literal["assistant"] | None = None
    content: str | None = None


class ChatCompletionResponseStreamChoice(BaseModel):
    """A single completion choice for streaming updates."""

    index: int = 0
    delta: ChatCompletionDelta
    finish_reason: Literal["stop", "length", "content_filter"] | None = None


class ChatCompletionStreamResponse(BaseModel):
    """OpenAI streaming chat completion response chunk."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{int(time.time())}")
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatCompletionResponseStreamChoice]


class ModelObject(BaseModel):
    """OpenAI model info schema."""

    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "localy"


class ModelListResponse(BaseModel):
    """List of models response."""

    object: Literal["list"] = "list"
    data: list[ModelObject]
