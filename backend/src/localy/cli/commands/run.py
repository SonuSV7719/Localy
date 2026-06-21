"""
localy run — Load a model and start interactive chat.
"""

from __future__ import annotations

import typer
from rich.console import Console

from localy.core.config import get_settings
from localy.core.logging import setup_logging

console = Console()


def run(
    model_spec: str = typer.Argument(
        ...,
        help="Model to run (e.g., 'llama3.1:8b'). Must be downloaded first.",
    ),
    context: int = typer.Option(
        None,
        "--context",
        "-c",
        help="Context length override. Default: auto-tuned.",
    ),
    temperature: float = typer.Option(
        0.7,
        "--temperature",
        "-t",
        help="Sampling temperature.",
    ),
    system_prompt: str = typer.Option(
        None,
        "--system",
        "-s",
        help="System prompt for the conversation.",
    ),
) -> None:
    """Load a model and start interactive chat.

    Auto-tunes inference parameters based on your hardware.
    Type your message and press Enter to chat. Ctrl+C to exit.

    Examples:
        localy run llama3.1:8b
        localy run qwen2.5:7b --temperature 0.5
        localy run llama3.1:8b --system "You are a helpful coding assistant"
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    console.print(f"\n[bold blue]🚀 Starting Localy[/bold blue] with {model_spec}\n")

    # Resolve model from registry
    from localy.inference.model_registry import ModelRegistry
    from localy.core.exceptions import ModelNotFoundError

    registry = ModelRegistry(settings.config_path)
    try:
        model, variant = registry.resolve(model_spec)
    except ModelNotFoundError as e:
        console.print(f"[red]Error:[/red] {e.message}")
        console.print("[dim]Run 'localy pull {model_spec}' first.[/dim]")
        raise typer.Exit(1) from e

    # Check if model is downloaded
    model_path = settings.models_path / variant.huggingface_file
    if not model_path.exists():
        console.print(f"[red]Model not downloaded.[/red] Run: localy pull {model_spec}")
        raise typer.Exit(1)

    # Run hardware probe and compute optimal config
    from localy.hardware.report import run_full_probe
    from localy.tuning.optimizer import compute_inference_config

    with console.status("[bold green]Probing hardware and auto-tuning..."):
        report = run_full_probe(settings.models_path)
        config = compute_inference_config(
            report=report,
            model_size_bytes=model_path.stat().st_size,
            requested_context=context,
            profile=settings.tuning_profile,
            thread_override=settings.thread_count_override,
            batch_override=settings.batch_size_override,
        )

    console.print(f"  Model:     [bold]{model.display_name}[/bold]")
    console.print(f"  Quant:     {variant.quantization}")
    console.print(f"  Threads:   {config.n_threads} gen / {config.n_threads_batch} batch")
    console.print(f"  Context:   {config.n_ctx}")
    console.print(f"  Batch:     {config.n_batch}")
    console.print(f"  GPU Layers: {config.n_gpu_layers}")
    console.print(f"  Profile:   {config.tuning_profile}")
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
                use_mlock=config.use_mlock,
                flash_attn=config.flash_attn,
                verbose=False,
            )

        console.print("[green]✓ Model loaded successfully![/green]\n")
        console.print("[dim]Type your message and press Enter. Ctrl+C to exit.[/dim]\n")

    except Exception as e:
        console.print(f"[red]Failed to load model:[/red] {e}")
        raise typer.Exit(1) from e

    # Interactive chat loop
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    try:
        while True:
            try:
                user_input = console.input("[bold cyan]You:[/bold cyan] ")
            except EOFError:
                break

            if not user_input.strip():
                continue

            if user_input.strip().lower() in {"/exit", "/quit", "/q"}:
                break

            messages.append({"role": "user", "content": user_input})

            console.print("[bold green]Assistant:[/bold green] ", end="")

            try:
                import time

                start = time.perf_counter()
                response = llm.create_chat_completion(
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=settings.default_context_length,
                    stream=True,
                )

                full_response = ""
                token_count = 0
                first_token_time = None

                for chunk in response:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                        console.print(content, end="")
                        full_response += content
                        token_count += 1

                elapsed = time.perf_counter() - start
                ttft = (first_token_time - start) * 1000 if first_token_time else 0
                tps = token_count / elapsed if elapsed > 0 else 0

                console.print()
                console.print(
                    f"[dim]  ({token_count} tokens, {tps:.1f} tok/s, "
                    f"TTFT: {ttft:.0f}ms, total: {elapsed:.1f}s)[/dim]\n"
                )

                messages.append({"role": "assistant", "content": full_response})

            except Exception as e:
                console.print(f"\n[red]Error during generation:[/red] {e}\n")

    except KeyboardInterrupt:
        console.print("\n\n[dim]Goodbye! 👋[/dim]\n")
