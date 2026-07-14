"""
Coordinator role — run a model split across the pool.

The coordinator holds the GGUF and spawns a `llama-server` subprocess that
offloads layers to the remote `ggml-rpc-server` workers (via `--rpc`) using the
memory-weighted `--tensor-split` from the shard planner. Localy proxies its
normal OpenAI/Ollama chat routes to this llama-server, so the pooled model is
served through the exact same API surface as solo mode.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx

from localy.core.config import Settings
from localy.core.exceptions import ClusterFormationError
from localy.core.logging import get_logger
from localy.pooling.binaries import llama_server_path
from localy.pooling.shard_planner import ShardPlan

logger = get_logger(__name__)


class Coordinator:
    """Supervises the llama-server subprocess that drives pooled inference."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._proc: subprocess.Popen | None = None
        self._host = "127.0.0.1"  # coordinator API is local; workers reached via --rpc
        self._port = settings.coordinator_port
        self._model_id: str | None = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def proxy_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def model_id(self) -> str | None:
        return self._model_id

    def start(
        self,
        model_id: str,
        model_path: Path,
        plan: ShardPlan,
        n_ctx: int = 4096,
        ready_timeout: float = 900.0,
    ) -> None:
        """Launch llama-server with the pool's RPC endpoints and tensor split.

        `ready_timeout` is generous by default: streaming layer weights to a slow
        remote worker (e.g. a phone over WiFi) can take several minutes.
        """
        if self.is_running:
            self.stop()

        binary = llama_server_path(self._settings)  # raises if not built
        endpoints = plan.rpc_endpoints
        if not endpoints:
            raise ClusterFormationError(
                "No remote workers in the shard plan; nothing to pool with."
            )

        # tensor-split proportions must align with device order:
        #   local device(s) first, then RPC devices in --rpc order.
        # The planner already orders nodes local-first.
        tensor_split = ",".join(f"{w:.4f}" for w in plan.tensor_split)

        cmd = [
            str(binary),
            "--model",
            str(model_path),
            "--rpc",
            ",".join(endpoints),
            "--tensor-split",
            tensor_split,
            "-ngl",
            "999",  # offload all layers across the (RPC) devices
            "--host",
            self._host,
            "--port",
            str(self._port),
            "-c",
            str(n_ctx),
        ]
        logger.info("starting_coordinator", model=model_id, cmd=" ".join(cmd))

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(binary.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            raise ClusterFormationError(f"Failed to launch llama-server: {e}") from e

        self._model_id = model_id
        if not self._wait_until_ready(timeout=ready_timeout):
            output = self._drain_output()
            self.stop()
            raise ClusterFormationError(
                f"Pooled llama-server did not become ready. Output:\n{output}"
            )
        logger.info("coordinator_ready", model=model_id, url=self.proxy_url)

    def _wait_until_ready(self, timeout: float) -> bool:
        """Poll llama-server /health until ready (weights stream to workers first)."""
        deadline = time.time() + timeout
        health = f"{self.proxy_url}/health"
        while time.time() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                return False  # process died
            try:
                r = httpx.get(health, timeout=2.0)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
        return False

    def _drain_output(self) -> str:
        if self._proc is None or self._proc.stdout is None:
            return ""
        try:
            return self._proc.stdout.read() or ""
        except Exception:
            return ""

    def stop(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        logger.info("coordinator_stopped", model=self._model_id)
        self._proc = None
        self._model_id = None
