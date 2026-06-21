"""
localy models — List available and downloaded models.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from localy.core.config import get_settings
from localy.core.constants import FitLevel
from localy.core.logging import setup_logging
from localy.hardware.report import run_full_probe
from localy.inference.model_registry import ModelRegistry
from localy.tuning.advisor import assess_model_fit

console = Console()


def models(
    show_fit: bool = typer.Option(
        True,
        "--fit/--no-fit",
        help="Show hardware fit assessment for each model.",
    ),
) -> None:
    """List available models from the curated registry.

    Shows all models with their quantization variants, file sizes,
    and whether they fit on your hardware.
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    console.print("\n[bold blue]📦 Localy Model Registry[/bold blue]\n")

    # Load registry
    registry = ModelRegistry(settings.config_path)
    all_models = registry.list_models()

    if not all_models:
        console.print("[yellow]No models in registry. Run 'localy pull' to add models.[/yellow]")
        return

    # Run hardware probe if showing fit
    report = None
    if show_fit:
        with console.status("[bold green]Probing hardware for fit assessment..."):
            report = run_full_probe(settings.models_path)

    # Build table
    table = Table(title="Available Models", show_header=True, header_style="bold cyan")
    table.add_column("Model", style="bold")
    table.add_column("Family")
    table.add_column("Params")
    table.add_column("Quant", style="dim")
    table.add_column("Size")
    table.add_column("Context")

    if show_fit:
        table.add_column("Fit", justify="center")

    # Check which models are downloaded
    downloaded_files = set()
    if settings.models_path.exists():
        downloaded_files = {f.name for f in settings.models_path.glob("*.gguf")}

    for model in all_models:
        for quant_name, variant in model.variants.items():
            # Check if downloaded
            is_downloaded = variant.huggingface_file in downloaded_files
            name_style = "bold green" if is_downloaded else ""
            status_prefix = "✓ " if is_downloaded else "  "

            row: list[str] = [
                f"{status_prefix}[{name_style}]{model.display_name}[/{name_style}]" if name_style else f"{status_prefix}{model.display_name}",
                model.family,
                f"{model.parameter_count_billions:.1f}B",
                quant_name,
                f"{variant.file_size_gb:.1f} GB",
                f"{model.context_length // 1024}K",
            ]

            if show_fit and report:
                assessment = assess_model_fit(
                    report=report,
                    model_name=model.display_name,
                    parameter_count_billions=model.parameter_count_billions,
                    quantization=quant_name,
                )
                fit_icon = {
                    FitLevel.FITS_WELL: "[green]✅ Fits well[/green]",
                    FitLevel.FITS_TIGHT: "[yellow]⚠️ Tight fit[/yellow]",
                    FitLevel.DOES_NOT_FIT: "[red]🔴 Too large[/red]",
                    FitLevel.UNKNOWN: "[dim]? Unknown[/dim]",
                }
                row.append(fit_icon.get(assessment.fit_level, "?"))

            table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]✓ = Downloaded  |  {len(all_models)} models available[/dim]")
    console.print("[dim]Use 'localy pull <model>' to download  |  'localy fit <model>' for detailed fit info[/dim]\n")
