"""
Localy CLI — command-line interface powered by Typer.

This is the primary Phase 1 interface. The CLI validates the core engine
(probe → tune → infer → benchmark) with zero UI overhead.

Commands:
    localy probe      — Detect and display hardware capabilities
    localy models     — List available and downloaded models
    localy pull       — Download a model from the registry
    localy fit        — Check if a model fits on this hardware
    localy run        — Load a model and start interactive chat
    localy benchmark  — Run performance benchmark
    localy serve      — Start the REST API server (Phase 1.5)
    localy version    — Show version information
"""

from __future__ import annotations

import typer
from rich.console import Console

from localy.version import __version__

# Main CLI app
app = typer.Typer(
    name="localy",
    help="Localy — Fast, accessible local LLM platform with auto-tuned inference.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold blue]Localy[/bold blue] v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Localy — Auto-tuned local LLM inference.

    Run [bold]localy probe[/bold] to start by detecting your hardware capabilities.
    """


# ===========================
# Import and register commands
# ===========================

from localy.cli.commands.probe import probe  # noqa: E402
from localy.cli.commands.models import models  # noqa: E402
from localy.cli.commands.pull import pull  # noqa: E402
from localy.cli.commands.fit import fit  # noqa: E402
from localy.cli.commands.run import run  # noqa: E402
from localy.cli.commands.benchmark import benchmark  # noqa: E402
from localy.cli.commands.serve import serve  # noqa: E402
from localy.cli.commands.worker import worker  # noqa: E402
from localy.cli.commands.pool import pool_app  # noqa: E402

app.command()(probe)
app.command()(models)
app.command()(pull)
app.command()(fit)
app.command()(run)
app.command()(benchmark)
app.command()(serve)
app.command()(worker)
app.add_typer(pool_app, name="pool")


if __name__ == "__main__":
    app()
