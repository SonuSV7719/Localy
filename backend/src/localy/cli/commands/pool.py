"""
localy pool — device pooling commands (Phase 3).

    localy pool status
    localy pool plan <model> --worker host:port [--worker ...]
    localy pool run  <model> --worker host:port [--worker ...] [--prompt "..."]

`run` is the Stage-1 vertical slice: join workers, plan the split, spawn the
pooled llama-server, and stream a test completion through it.
"""

from __future__ import annotations

import json

import httpx
import typer
from rich.console import Console

from localy.core.config import get_settings
from localy.core.logging import setup_logging
from localy.services.pool_service import get_pool_service

console = Console()
pool_app = typer.Typer(name="pool", no_args_is_help=True, help="Device pooling (Phase 3).")


def _parse_worker(addr: str) -> tuple[str, int]:
    if ":" not in addr:
        raise typer.BadParameter(f"Worker must be host:port, got '{addr}'")
    host, _, port = addr.rpartition(":")
    return host, int(port)


def _join_workers(service, workers: list[str]) -> None:
    for addr in workers:
        host, port = _parse_worker(addr)
        node = service.join(host, port)
        console.print(f"  + joined worker [cyan]{node.address}[/cyan]")


@pool_app.command("status")
def status() -> None:
    """Show the current pool status."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    st = get_pool_service(settings).status()
    console.print_json(json.dumps(st))


@pool_app.command("plan")
def plan(
    model: str = typer.Argument(..., help="Model id, e.g. llama3.1:8b"),
    workers: list[str] = typer.Option([], "--worker", "-w", help="Worker host:port (repeatable)."),
) -> None:
    """Show how a model would be split across the pool (no load)."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    service = get_pool_service(settings)
    _join_workers(service, workers)
    result = service.plan_for_model(model)
    console.print_json(json.dumps(result.to_dict()))


@pool_app.command("run")
def run(
    model: str = typer.Argument(..., help="Model id, e.g. llama3.1:8b (must be downloaded)."),
    workers: list[str] = typer.Option([], "--worker", "-w", help="Worker host:port (repeatable)."),
    prompt: str = typer.Option("Say hello in one short sentence.", "--prompt", help="Test prompt."),
    ctx: int = typer.Option(4096, "--ctx", help="Context length."),
) -> None:
    """Load a model split across the pool and stream a test completion."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    service = get_pool_service(settings)

    if not workers:
        console.print("[red]Provide at least one --worker host:port.[/red]")
        raise typer.Exit(code=1)

    _join_workers(service, workers)

    console.print(f"\n[bold]Planning[/bold] '{model}' across the pool...")
    plan_result = service.plan_for_model(model)
    console.print_json(json.dumps(plan_result.to_dict()))
    if not plan_result.fits:
        console.print("[red]Model does not fit across the pool.[/red]")
        raise typer.Exit(code=1)

    console.print("\n[bold]Starting pooled llama-server[/bold] (streaming weights to workers)...")
    try:
        service.load_pooled(model, n_ctx=ctx)
    except Exception as e:
        console.print(f"[red]Failed to start pooled inference: {e}[/red]")
        raise typer.Exit(code=1)

    url = f"{service.proxy_url}/v1/chat/completions"
    console.print(f"[green]Pooled model ready[/green] at {service.proxy_url}\n")
    console.print(f"[dim]Prompt:[/dim] {prompt}\n[bold]Response:[/bold] ", end="")

    try:
        with httpx.stream(
            "POST",
            url,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            },
            timeout=120.0,
        ) as r:
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    tok = json.loads(data)["choices"][0]["delta"].get("content", "")
                    console.print(tok, end="")
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
        console.print("\n")
    finally:
        console.print("[dim]Stopping pooled server...[/dim]")
        service.unload_pooled()
