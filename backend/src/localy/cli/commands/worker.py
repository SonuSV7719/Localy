"""
localy worker — run this device as a pool worker (Phase 3).

Starts a llama.cpp rpc-server that exposes this machine's memory/compute to a
coordinator on the LAN. The worker needs no model file. Press Ctrl+C to stop.
"""

from __future__ import annotations

import time

import typer
from rich.console import Console

from localy.core.config import get_settings
from localy.core.logging import setup_logging
from localy.pooling.binaries import binaries_available
from localy.pooling.discovery import WorkerAdvertiser
from localy.pooling.worker import WorkerProcess, compute_local_capacity

console = Console()


def worker(
    port: int = typer.Option(None, "--port", "-p", help="Port to listen on. Default: 50052."),
    mem: int = typer.Option(
        None, "--mem", "-m", help="Memory to offer in MiB. Default: auto (from hardware probe)."
    ),
) -> None:
    """Run this device as a Localy pool worker (llama.cpp rpc-server)."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    if not binaries_available(settings):
        console.print(
            "[bold red]RPC binaries not found.[/bold red] Build them first:\n"
            "  [cyan]scripts\\build-llama-rpc.bat[/cyan]  (from the repo root)"
        )
        raise typer.Exit(code=1)

    cap = compute_local_capacity(settings)
    bind_port = port or settings.rpc_port
    offer_mib = mem or cap.offered_mib

    proc = WorkerProcess(settings)
    advertiser = WorkerAdvertiser(port=bind_port, label="", budget_bytes=cap.offered_bytes)
    console.print("\n[bold blue]🔗 Localy Pool Worker[/bold blue]\n")
    console.print(f"  Offering:  {offer_mib} MiB (~{offer_mib/1024:.1f} GB) of memory")
    console.print(f"  Listening: {settings.rpc_bind_host}:{bind_port}")
    console.print("\n[dim]Advertising over your network — the coordinator will find it automatically. Ctrl+C to stop.[/dim]\n")

    try:
        proc.start(port=bind_port, mem_mib=offer_mib)
        advertiser.start()  # announce over mDNS so coordinators auto-discover us
        console.print("[green]Worker running.[/green] Waiting for the coordinator to connect...")
        while proc.is_running:
            time.sleep(1)
        console.print("[yellow]Worker process exited.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping worker...[/yellow]")
    finally:
        advertiser.stop()
        proc.stop()
