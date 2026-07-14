"""
Worker role — expose this device's compute/memory to the pool.

A worker runs an `ggml-rpc-server` subprocess that the coordinator's
`llama-server` offloads model layers to. The worker needs NO model file — the
coordinator streams the relevant tensors to it at load time.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from localy.core.config import Settings
from localy.core.constants import POOL_MEMORY_OFFER_FRACTION
from localy.core.exceptions import PoolingError
from localy.core.logging import get_logger
from localy.hardware.report import run_full_probe
from localy.pooling.binaries import rpc_server_path

logger = get_logger(__name__)


@dataclass
class WorkerCapacity:
    """How much this device offers to the pool."""

    offered_bytes: int
    total_bytes: int
    cpu_threads: int

    @property
    def offered_mib(self) -> int:
        return int(self.offered_bytes / (1024**2))


def compute_local_capacity(settings: Settings) -> WorkerCapacity:
    """Derive how much memory/compute this device should offer to the pool.

    Uses the same hardware probe that drives solo tuning, so the number is the
    honest "safe" budget, scaled by POOL_MEMORY_OFFER_FRACTION.
    """
    report = run_full_probe(settings.models_path)
    safe = report.memory.safe_model_budget_bytes
    offered = int(safe * POOL_MEMORY_OFFER_FRACTION)
    return WorkerCapacity(
        offered_bytes=offered,
        total_bytes=report.memory.total_bytes,
        cpu_threads=report.cpu.recommended_generation_threads,
    )


class WorkerProcess:
    """Supervises a single ggml-rpc-server subprocess."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._proc: subprocess.Popen | None = None
        self._host = settings.rpc_bind_host
        self._port = settings.rpc_port

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def address(self) -> str:
        return f"{self._host}:{self._port}"

    def start(self, port: int | None = None, mem_mib: int | None = None) -> None:
        """Launch the rpc-server. Raises PoolingError on failure."""
        if self.is_running:
            raise PoolingError("Worker already running.")

        binary = rpc_server_path(self._settings)  # raises if not built
        self._port = port or self._settings.rpc_port

        # NOTE: this ggml-rpc-server build reports its own memory automatically
        # and has no --mem flag. `mem_mib` is used only for advertising capacity
        # (discovery / shard planning), not passed to the binary.
        cap = compute_local_capacity(self._settings)
        cmd = [
            str(binary),
            "--host",
            self._host,
            "--port",
            str(self._port),
            "--threads",
            str(cap.cpu_threads),
            "--cache",  # persist tensors so models aren't re-streamed each reconnect
        ]
        logger.info("starting_rpc_worker", cmd=" ".join(cmd), offer_mib=mem_mib or cap.offered_mib)

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(binary.parent),  # so it finds ggml/llama DLLs
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            raise PoolingError(f"Failed to launch rpc-server: {e}") from e

        # Fail fast if it died immediately (e.g. port in use, missing DLL).
        try:
            rc = self._proc.wait(timeout=1.5)
            output = self._proc.stdout.read() if self._proc.stdout else ""
            raise PoolingError(
                f"rpc-server exited immediately (code {rc}). Output:\n{output}"
            )
        except subprocess.TimeoutExpired:
            pass  # still running — good

        logger.info("rpc_worker_started", address=self.address, pid=self._proc.pid)

    def stop(self) -> None:
        """Terminate the worker subprocess."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        logger.info("rpc_worker_stopped", address=self.address)
        self._proc = None
