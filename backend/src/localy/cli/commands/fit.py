"""
localy fit — Check if a model fits on this hardware.
"""

from __future__ import annotations

import typer
from rich.console import Console

from localy.core.config import get_settings
from localy.core.constants import FitLevel
from localy.core.exceptions import ModelNotFoundError
from localy.core.logging import setup_logging
from localy.hardware.report import run_full_probe
from localy.inference.model_registry import ModelRegistry
from localy.tuning.advisor import assess_model_fit

console = Console()


def fit(
    model_spec: str = typer.Argument(
        ...,
        help="Model to check (e.g., 'llama3.1:8b', 'phi-4:14b').",
    ),
    context: int = typer.Option(
        4096,
        "--context",
        "-c",
        help="Target context length to check fit for.",
    ),
) -> None:
    """Check if a model fits on your hardware.

    Computes memory requirements and compares against your available budget.
    Shows detailed breakdown and recommendations.

    Examples:
        localy fit llama3.1:8b
        localy fit phi-4:14b --context 8192
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    console.print(f"\n[bold blue]🔎 Checking fit:[/bold blue] {model_spec}\n")

    # Resolve model
    registry = ModelRegistry(settings.config_path)
    try:
        model, variant = registry.resolve(model_spec)
    except ModelNotFoundError as e:
        console.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(1) from e

    # Run hardware probe
    with console.status("[bold green]Probing hardware..."):
        report = run_full_probe(settings.models_path)

    # Assess fit
    assessment = assess_model_fit(
        report=report,
        model_name=model.display_name,
        parameter_count_billions=model.parameter_count_billions,
        quantization=variant.quantization,
        target_context=context,
    )

    # Display results
    fit_styles = {
        FitLevel.FITS_WELL: ("green", "✅"),
        FitLevel.FITS_TIGHT: ("yellow", "⚠️"),
        FitLevel.DOES_NOT_FIT: ("red", "🔴"),
        FitLevel.UNKNOWN: ("dim", "❓"),
    }
    color, icon = fit_styles.get(assessment.fit_level, ("white", "?"))

    console.print(f"  {assessment.explanation}\n")

    console.print("  [bold]Memory Breakdown:[/bold]")
    console.print(f"    Model size:      {assessment.model_size_bytes / (1024**3):.1f} GB")
    console.print(f"    Total needed:    {assessment.memory_usage_bytes / (1024**3):.1f} GB (model + KV cache at ctx={context})")
    console.print(f"    Your budget:     {assessment.memory_budget_bytes / (1024**3):.1f} GB")
    console.print(f"    Headroom:        [{color}]{assessment.headroom_bytes / (1024**3):.1f} GB[/{color}]")
    console.print(f"    Max context:     {assessment.max_context} tokens")

    if assessment.recommendations:
        console.print("\n  [bold]Recommendations:[/bold]")
        for rec in assessment.recommendations:
            console.print(f"    • {rec}")

    console.print()
