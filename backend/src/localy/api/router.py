"""
Localy Master Router.

Combines OpenAI-compatible (v1), Ollama-compatible, and system monitoring API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from localy.api.v1 import v1_router
from localy.api.ollama import ollama_router
from localy.api.system import system_router

api_router = APIRouter()

# Include sub-routers
api_router.include_router(v1_router)
api_router.include_router(ollama_router)
api_router.include_router(system_router)
