"""
localy probe — Detect and display hardware capabilities.

This is the first command a user should run. It detects CPU, GPU, memory,
storage, and instruction set capabilities, then displays a detailed report.
"""

from __future__ import annotations

import typer
from rich.console import Console

from localy.core.config import get_settings
from localy.core.logging import setup_logging
from localy.hardware.report import run_full_probe

console = Console()


def probe(
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON instead of human-readable report.",
    ),
    save: bool = typer.Option(
        True,
        "--save/--no-save",
        help="Save report to disk for future use.",
    ),
) -> None:
    """Detect and display hardware capabilities.

    Runs a full hardware probe: CPU topology (P-cores/E-cores), GPU detection,
    memory analysis, storage speed, and instruction set detection.
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    console.print("\n[bold blue]🔍 Localy Hardware Probe[/bold blue]\n")
    console.print("Detecting hardware capabilities...\n")

    with console.status("[bold green]Probing hardware..."):
        report = run_full_probe(settings.models_path)

    if json_output:
        import json

        console.print_json(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        console.print(report.detailed_report)

    if save:
        report_path = settings.config_path / "hardware_report.json"
        report.save(report_path)
        console.print(f"\n[dim]Report saved to: {report_path}[/dim]")

    console.print()
