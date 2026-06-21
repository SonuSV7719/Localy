"""
Ollama-compatible router re-exports.
"""

from localy.api.ollama.endpoints import ollama_router

__all__ = ["ollama_router"]
