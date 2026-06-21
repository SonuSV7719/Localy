"""
localy benchmark — Run performance benchmark and report tok/s.
"""

from __future__ import annotations

import time

import typer
from rich.console import Console
from rich.table import Table

from localy.core.config import get_settings
from localy.core.constants import BENCHMARK_ITERATIONS, BENCHMARK_MAX_TOKENS, BENCHMARK_PROMPT
from localy.core.exceptions import ModelNotFoundError
from localy.core.logging import setup_logging

console = Console()


def benchmark(
    model_spec: str = typer.Argument(
        ...,
        help="Model to benchmark (e.g., 'llama3.1:8b'). Must be downloaded.",
    ),
    iterations: int = typer.Option(
        BENCHMARK_ITERATIONS,
        "--iterations",
        "-n",
        help="Number of benchmark iterations (reports median).",
    ),
    max_tokens: int = typer.Option(
        BENCHMARK_MAX_TOKENS,
        "--max-tokens",
        help="Maximum tokens to generate per iteration.",
    ),
) -> None:
    """Run a performance benchmark and report tok/s.

    Uses a standardized prompt for reproducible results.
    Reports median of N iterations to eliminate outliers.
    Stores results for historical comparison.

    Examples:
        localy benchmark llama3.1:8b
        localy benchmark qwen2.5:7b --iterations 5
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    console.print(f"\n[bold blue]⚡ Localy Benchmark[/bold blue] — {model_spec}\n")

    # Resolve and check model
    from localy.inference.model_registry import ModelRegistry

    registry = ModelRegistry(settings.config_path)
    try:
        model, variant = registry.resolve(model_spec)
    except ModelNotFoundError as e:
        console.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(1) from e

    model_path = settings.models_path / variant.huggingface_file
    if not model_path.exists():
        console.print(f"[red]Model not downloaded.[/red] Run: localy pull {model_spec}")
        raise typer.Exit(1)

    # Hardware probe and auto-tune
    from localy.hardware.report import run_full_probe
    from localy.tuning.optimizer import compute_inference_config

    with console.status("[bold green]Probing hardware..."):
        report = run_full_probe(settings.models_path)
        config = compute_inference_config(
            report=report,
            model_size_bytes=model_path.stat().st_size,
            profile=settings.tuning_profile,
        )

    console.print(f"  Config: {config.n_threads} threads, ctx={config.n_ctx}, batch={config.n_batch}")
    console.print(f"  Profile: {config.tuning_profile}")
    console.print()

    # Load model
    try:
        from llama_cpp import Llama

        with console.status("[bold green]Loading model..."):
            llm = Llama(
                model_path=str(model_path),
                n_ctx=config.n_ctx,
                n_threads=config.n_threads,
                n_threads_batch=config.n_threads_batch,
                n_batch=config.n_batch,
                n_gpu_layers=config.n_gpu_layers,
                use_mmap=config.use_mmap,
                verbose=False,
            )

        console.print("[green]✓ Model loaded[/green]\n")

    except Exception as e:
        console.print(f"[red]Failed to load model:[/red] {e}")
        raise typer.Exit(1) from e

    # Warmup
    console.print("[dim]Running warmup...[/dim]")
    try:
        llm.create_chat_completion(
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=16,
            temperature=0.0,
        )
    except Exception:
        pass

    # Run benchmark iterations
    results: list[dict[str, float]] = []

    for i in range(iterations):
        console.print(f"[dim]  Iteration {i + 1}/{iterations}...[/dim]", end="")

        start = time.perf_counter()
        first_token_time = None
        token_count = 0

        response = llm.create_chat_completion(
            messages=[{"role": "user", "content": BENCHMARK_PROMPT}],
            max_tokens=max_tokens,
            temperature=0.0,  # Deterministic for reproducibility
            stream=True,
        )

        for chunk in response:
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if content:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                token_count += 1

        elapsed = time.perf_counter() - start
        ttft = (first_token_time - start) * 1000 if first_token_time else 0
        gen_time = time.perf_counter() - first_token_time if first_token_time else elapsed
        tps = (token_count - 1) / gen_time if gen_time > 0 and token_count > 1 else 0

        results.append({
            "tokens": token_count,
            "total_time": elapsed,
            "ttft_ms": ttft,
            "generation_tps": tps,
        })

        console.print(f" {tps:.1f} tok/s ({token_count} tokens)")

    # Compute median
    sorted_by_tps = sorted(results, key=lambda r: r["generation_tps"])
    median_result = sorted_by_tps[len(sorted_by_tps) // 2]

    console.print()

    # Results table
    table = Table(title="Benchmark Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Model", model.display_name)
    table.add_row("Quantization", variant.quantization)
    table.add_row("Iterations", str(iterations))
    table.add_row("Tokens Generated", str(int(median_result["tokens"])))
    table.add_row("[bold]Generation Speed[/bold]", f"[bold green]{median_result['generation_tps']:.1f} tok/s[/bold green]")
    table.add_row("Time to First Token", f"{median_result['ttft_ms']:.0f} ms")
    table.add_row("Total Time", f"{median_result['total_time']:.1f} s")
    table.add_row("Tuning Profile", config.tuning_profile)
    table.add_row("Hardware Hash", report.hardware_hash)

    console.print(table)

    # Save results
    import json
    from datetime import datetime, timezone

    result_data = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "model": model.display_name,
        "quantization": variant.quantization,
        "hardware_hash": report.hardware_hash,
        "hardware_summary": report.summary,
        "config": {
            "n_threads": config.n_threads,
            "n_threads_batch": config.n_threads_batch,
            "n_batch": config.n_batch,
            "n_ctx": config.n_ctx,
            "profile": config.tuning_profile,
        },
        "results": {
            "median_tps": median_result["generation_tps"],
            "median_ttft_ms": median_result["ttft_ms"],
            "iterations": [r for r in results],
        },
    }

    results_dir = settings.benchmarks_path
    results_dir.mkdir(parents=True, exist_ok=True)
    result_file = results_dir / f"benchmark_{report.hardware_hash}_{int(time.time())}.json"
    result_file.write_text(json.dumps(result_data, indent=2), encoding="utf-8")

    console.print(f"\n[dim]Results saved to: {result_file}[/dim]")
    console.print(
        f"\n[bold]Expected performance on this device: "
        f"~{median_result['generation_tps']:.0f} tok/s for {model.display_name}[/bold]\n"
    )
