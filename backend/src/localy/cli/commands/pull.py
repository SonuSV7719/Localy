"""
localy pull — Download a model from the curated registry.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn

from localy.core.config import get_settings
from localy.core.constants import FitLevel
from localy.core.exceptions import DownloadError, ModelNotFoundError
from localy.core.logging import setup_logging
from localy.hardware.report import run_full_probe
from localy.tuning.advisor import assess_model_fit
from localy.inference.model_registry import ModelRegistry
from localy.utils.download import download_file

console = Console()


def pull(
    model_spec: str = typer.Argument(
        ...,
        help="Model to download (e.g., 'llama3.1:8b', 'llama3.1:8b-q4_k_m').",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Re-download even if already present.",
    ),
    skip_fit_check: bool = typer.Option(
        False,
        "--skip-fit-check",
        help="Skip the pre-download fit check.",
    ),
) -> None:
    """Download a model from the Localy registry.

    Checks hardware fit BEFORE downloading to avoid wasting bandwidth
    on models that won't run well on your device.

    Examples:
        localy pull llama3.1:8b
        localy pull qwen2.5:7b-q8_0
        localy pull smollm2:2b
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    console.print(f"\n[bold blue]⬇ Pulling model:[/bold blue] {model_spec}\n")

    # Resolve model from registry
    registry = ModelRegistry(settings.config_path)
    try:
        model, variant = registry.resolve(model_spec)
    except ModelNotFoundError as e:
        console.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(1) from e

    console.print(f"  Model:    [bold]{model.display_name}[/bold]")
    console.print(f"  Quant:    {variant.quantization}")
    console.print(f"  Size:     {variant.file_size_gb:.1f} GB")
    console.print(f"  Source:   {variant.huggingface_repo}")
    console.print()

    # Check if already downloaded
    destination = settings.models_path / variant.huggingface_file
    if destination.exists() and not force:
        console.print("[green]✓ Model already downloaded![/green]")
        console.print(f"  Path: {destination}")
        console.print("[dim]  Use --force to re-download.[/dim]\n")
        return

    # Pre-download fit check
    if not skip_fit_check:
        console.print("[dim]Checking hardware fit...[/dim]")
        report = run_full_probe(settings.models_path)
        assessment = assess_model_fit(
            report=report,
            model_name=model.display_name,
            parameter_count_billions=model.parameter_count_billions,
            quantization=variant.quantization,
        )

        console.print(f"\n  {assessment.explanation}\n")

        if assessment.fit_level == FitLevel.DOES_NOT_FIT:
            console.print("[yellow]This model won't fit on your device.[/yellow]")
            for rec in assessment.recommendations:
                console.print(f"  • {rec}")
            console.print()
            if not typer.confirm("Download anyway?", default=False):
                console.print("[dim]Download cancelled.[/dim]\n")
                raise typer.Exit(0)

    # Check disk space
    if not settings.models_path.exists():
        settings.models_path.mkdir(parents=True, exist_ok=True)

    # Download with progress bar
    url = variant.resolved_download_url
    console.print(f"[dim]Downloading from: {url}[/dim]\n")

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    task_id = None

    def progress_callback(downloaded: int, total: int, speed_mbps: float) -> None:
        nonlocal task_id
        if task_id is None:
            task_id = progress.add_task("Downloading", total=total)
        progress.update(task_id, completed=downloaded)

    try:
        with progress:
            asyncio.run(
                download_file(
                    url=url,
                    destination=destination,
                    expected_sha256=variant.sha256 or None,
                    progress_callback=progress_callback,
                )
            )
    except DownloadError as e:
        console.print(f"\n[red]Download failed:[/red] {e.message}")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        console.print("\n[yellow]Download cancelled. Partial file preserved for resume.[/yellow]\n")
        raise typer.Exit(0)

    console.print(f"\n[green]✓ Model downloaded successfully![/green]")
    console.print(f"  Saved to: {destination}")
    console.print(f"  Run with: [bold]localy run {model_spec}[/bold]\n")
