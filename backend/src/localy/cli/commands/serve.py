"""
localy serve — Start the REST API server (Phase 1.5).

Starts a FastAPI server with both OpenAI-compatible and Ollama-compatible
API endpoints, making Localy usable with existing tools.
"""

from __future__ import annotations

import typer
from rich.console import Console

from localy.core.config import get_settings
from localy.core.logging import setup_logging

console = Console()


def serve(
    host: str = typer.Option(
        None,
        "--host",
        "-h",
        help="Bind address. Default: 127.0.0.1 (localhost only).",
    ),
    port: int = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to listen on. Default: 11434.",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Enable auto-reload for development.",
    ),
) -> None:
    """Start the Localy REST API server.

    Exposes OpenAI-compatible and Ollama-compatible API endpoints.
    Existing tools (Open WebUI, IDE extensions, etc.) work immediately.

    Endpoints:
        /v1/chat/completions  — OpenAI-compatible chat
        /v1/models            — List models
        /api/generate         — Ollama-compatible generate
        /api/chat             — Ollama-compatible chat
        /api/tags             — List models (Ollama format)
        /health               — Health check
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    bind_host = host or settings.host
    bind_port = port or settings.port

    console.print(f"\n[bold blue]🌐 Localy API Server[/bold blue]\n")
    console.print(f"  Listening on: http://{bind_host}:{bind_port}")
    console.print(f"  OpenAI API:   http://{bind_host}:{bind_port}/v1/chat/completions")
    console.print(f"  Ollama API:   http://{bind_host}:{bind_port}/api/chat")
    console.print(f"  Health:       http://{bind_host}:{bind_port}/health")
    console.print()
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    import sys
    import uvicorn
    from localy.main import create_app

    if getattr(sys, "frozen", False):
        uvicorn.run(
            create_app(),
            host=bind_host,
            port=bind_port,
            reload=False,
            log_level=settings.log_level.lower(),
        )
    else:
        uvicorn.run(
            "localy.main:create_app",
            host=bind_host,
            port=bind_port,
            reload=reload,
            factory=True,
            log_level=settings.log_level.lower(),
        )
