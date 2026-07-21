"""
Coordinator role — run a model split across the pool.

The coordinator holds the GGUF and spawns a `llama-server` subprocess that
offloads layers to the remote `ggml-rpc-server` workers (via `--rpc`) using the
memory-weighted `--tensor-split` from the shard planner. Localy proxies its
normal OpenAI/Ollama chat routes to this llama-server, so the pooled model is
served through the exact same API surface as solo mode.

Loading is **non-blocking**: `start()` returns immediately after spawning the
process, and a background monitor thread tracks readiness while parsing the
subprocess output for progress. Callers poll `progress()` (surfaced through
`/pool/status`) so the UI can show live status that survives tab switches —
the state lives here on the server, not in any one client.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import httpx

from localy.core.config import Settings
from localy.core.exceptions import ClusterFormationError
from localy.core.logging import get_logger
from localy.pooling.binaries import llama_server_path
from localy.pooling.shard_planner import ShardPlan

logger = get_logger(__name__)

# Best-effort progress signals parsed from llama-server stdout/stderr.
_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")

# llama-server doesn't print a clean load percentage, but it does print
# recognisable phase markers. We map each to a monotonic progress fraction and a
# human-readable stage label so the UI shows a moving bar + meaningful status
# even without a numeric percent. Checked in order; later matches win.
_LOAD_MARKERS: list[tuple[str, float, str]] = [
    ("load_model", 0.05, "Reading model file"),
    ("loading model", 0.05, "Reading model file"),
    ("llama_model_loader", 0.12, "Reading model metadata"),
    ("loaded meta data", 0.15, "Reading model metadata"),
    ("load_tensors", 0.25, "Loading tensors"),
    ("loading model tensors", 0.25, "Loading tensors"),
    ("model buffer size", 0.45, "Streaming layers to worker devices"),
    ("rpc", 0.50, "Streaming layers to worker devices"),
    ("kv cache", 0.85, "Allocating KV cache"),
    ("kv_cache", 0.85, "Allocating KV cache"),
    ("kv buffer", 0.85, "Allocating KV cache"),
    ("warming up", 0.92, "Warming up"),
    ("model loaded", 0.96, "Finalizing"),
    ("server is listening", 0.98, "Finalizing"),
]
# Per-device allocation lines, e.g. "... model buffer size = 336.00 MiB".
_BUFFER_RE = re.compile(r"buffer size\s*=\s*([\d.]+)\s*MiB", re.IGNORECASE)

# The phase-fraction band during which weights actually stream to workers:
# tensor loading (~0.25) through "model loaded" (~0.96). We map the coarse
# phase fraction onto 0..1 inside this band to derive an *estimated* bytes-sent
# / speed / ETA readout. llama.cpp doesn't emit a byte-exact RPC counter, so
# these are clearly labelled estimates — but they give the user the live
# "X of Y transferred, ~N MB/s, ~T left" feedback they expect during a load.
_TRANSFER_BAND_START = 0.25
_TRANSFER_BAND_END = 0.96


class Coordinator:
    """Supervises the llama-server subprocess that drives pooled inference."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._proc: subprocess.Popen | None = None
        self._host = "127.0.0.1"  # coordinator API is local; workers reached via --rpc
        self._port = settings.coordinator_port
        self._model_id: str | None = None

        # --- progress state (guarded by _lock) ---
        self._lock = threading.Lock()
        self._phase = "idle"          # idle | starting | loading | ready | error | stopped
        self._stage = ""              # granular human label parsed from output
        self._ready = False
        self._error: str | None = None
        self._started_at = 0.0
        self._ready_at = 0.0
        self._last_log_at = 0.0       # wall time of the last log line (stall detection)
        self._progress_frac: float | None = None  # 0..1 if parseable from output
        self._transfer_started_at = 0.0  # when weight-streaming began (for speed/ETA)
        self._bytes_total = 0         # approx bytes to stream to remote workers
        self._node_count = 0
        self._remote_count = 0
        self._last_log = ""
        self._log_tail: deque[str] = deque(maxlen=200)
        self._cancelling = False      # user asked to stop; suppress "failed" reporting
        self._reader: threading.Thread | None = None
        self._monitor: threading.Thread | None = None

    # --- lifecycle ---------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def is_ready(self) -> bool:
        return self.is_running and self._ready

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
        """Spawn llama-server and return immediately.

        Readiness (weights streaming to remote workers, which can take minutes
        over WiFi) is tracked in the background; poll `progress()`.
        """
        if self.is_running:
            self.stop()

        binary = llama_server_path(self._settings)  # raises if not built
        endpoints = plan.rpc_endpoints
        if not endpoints:
            raise ClusterFormationError(
                "No remote workers in the shard plan; nothing to pool with."
            )

        # How much weight data must stream to the remote (non-local) devices —
        # the local device's share stays in local memory. Used for the UI's
        # "X of Y transferred" readout.
        remote_frac = sum(
            w for n, w in zip(plan.nodes, plan.tensor_split) if not n.is_local
        )
        bytes_total = int(plan.model_size_bytes * max(0.0, min(1.0, remote_frac)))

        # tensor-split proportions must align with device order:
        #   local device(s) first, then RPC devices in --rpc order.
        tensor_split = ",".join(f"{w:.4f}" for w in plan.tensor_split)

        cmd = [
            str(binary),
            "--model", str(model_path),
            "--rpc", ",".join(endpoints),
            "--tensor-split", tensor_split,
            "-ngl", "999",  # offload all layers across the (RPC) devices
            "--host", self._host,
            "--port", str(self._port),
            "-c", str(n_ctx),
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

        with self._lock:
            self._model_id = model_id
            self._phase = "starting"
            self._stage = "Starting coordinator…"
            self._cancelling = False
            self._last_log_at = time.time()
            self._ready = False
            self._error = None
            self._started_at = time.time()
            self._ready_at = 0.0
            self._progress_frac = None
            self._transfer_started_at = 0.0
            self._bytes_total = bytes_total
            self._node_count = len(plan.nodes)
            self._remote_count = len(endpoints)
            self._last_log = ""
            self._log_tail.clear()

        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()
        self._monitor = threading.Thread(
            target=self._await_ready, args=(ready_timeout,), daemon=True
        )
        self._monitor.start()

    # --- background threads ------------------------------------------------

    def _read_output(self) -> None:
        """Stream subprocess output → progress signals + a rolling log tail."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if not line:
                    continue
                self._ingest_line(line)
        except Exception:  # pragma: no cover - stream closed mid-read
            pass

    def _ingest_line(self, line: str) -> None:
        low = line.lower()
        with self._lock:
            self._last_log = line[:300]
            self._last_log_at = time.time()
            self._log_tail.append(line[:300])

            if self._phase == "starting":
                self._phase = "loading"

            # Advance the progress fraction monotonically from phase markers, so
            # the bar only ever moves forward regardless of log ordering.
            for marker, frac, label in _LOAD_MARKERS:
                if marker in low:
                    if self._progress_frac is None or frac > self._progress_frac:
                        self._progress_frac = frac
                    self._stage = label

            # If the loader ever does print an explicit percentage, map it into
            # the tensor-loading band (25%–90%) and take the max.
            m = _PCT_RE.search(line)
            if m:
                try:
                    p = float(m.group(1)) / 100.0
                    if 0.0 <= p <= 1.0:
                        mapped = 0.25 + p * (0.90 - 0.25)
                        if self._progress_frac is None or mapped > self._progress_frac:
                            self._progress_frac = mapped
                except ValueError:
                    pass

    def _await_ready(self, timeout: float) -> None:
        """Poll llama-server /health until ready, the process dies, or timeout."""
        deadline = time.time() + timeout
        health = f"{self.proxy_url}/health"
        while time.time() < deadline:
            if self._cancelling:
                return  # user cancelled; stop() handles state
            proc = self._proc
            if proc is None or proc.poll() is not None:
                if self._cancelling:
                    return
                self._fail("The pooled server process exited during startup.")
                return
            try:
                r = httpx.get(health, timeout=2.0)
                if r.status_code == 200:
                    with self._lock:
                        self._ready = True
                        self._phase = "ready"
                        self._stage = "Ready"
                        self._ready_at = time.time()
                        self._progress_frac = 1.0
                    logger.info("coordinator_ready", model=self._model_id, url=self.proxy_url)
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
        self._fail("Timed out waiting for the pooled server to become ready.")

    def _fail(self, message: str) -> None:
        with self._lock:
            tail = "\n".join(list(self._log_tail)[-20:])
            self._error = f"{message}\n{tail}".strip()
            self._phase = "error"
            self._ready = False
        logger.warning("coordinator_failed", model=self._model_id, error=message)
        # Reap the process if it's still hanging around.
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # --- introspection -----------------------------------------------------

    def progress(self) -> dict:
        """Snapshot of load state for the UI. Safe to call frequently."""
        with self._lock:
            active = self.is_running and not self._ready and self._error is None
            elapsed = 0.0
            if self._started_at:
                end = self._ready_at if self._ready_at else time.time()
                elapsed = max(0.0, end - self._started_at)
            frac = self._progress_frac
            # Seconds since the loader last emitted anything — a stall indicator.
            # llama.cpp is silent while streaming weights to a slow RPC worker,
            # so a large value here means "still working on a long step", not dead.
            idle = 0.0
            if active and self._last_log_at:
                idle = max(0.0, time.time() - self._last_log_at)

            # --- estimated transfer readout (bytes sent / speed / ETA) ---------
            # percent is a coarse *phase* estimate parsed from log markers, not a
            # byte counter, so everything derived from it is an estimate too.
            # We map the phase fraction onto the weight-streaming band to get a
            # transfer fraction, then derive bytes-sent, a cumulative transfer
            # speed, and an ETA. All flagged with *_is_estimate so the UI can be
            # honest ("~") rather than implying exact byte accounting.
            bytes_sent: int | None = None
            eta_s: float | None = None
            speed_bps: float | None = None
            if frac is not None and self._bytes_total > 0:
                span = _TRANSFER_BAND_END - _TRANSFER_BAND_START
                transfer_frac = (frac - _TRANSFER_BAND_START) / span
                transfer_frac = max(0.0, min(1.0, transfer_frac))
                if self._ready:
                    transfer_frac = 1.0
                bytes_sent = int(self._bytes_total * transfer_frac)

                # Mark when streaming began so speed reflects the transfer, not
                # the earlier metadata-reading phase.
                if transfer_frac > 0.0 and self._transfer_started_at == 0.0:
                    self._transfer_started_at = time.time()
                if self._transfer_started_at:
                    end = self._ready_at if self._ready_at else time.time()
                    t_elapsed = max(0.0, end - self._transfer_started_at)
                    if t_elapsed > 1.0 and bytes_sent > 0:
                        speed_bps = bytes_sent / t_elapsed
                        remaining = max(0, self._bytes_total - bytes_sent)
                        if speed_bps > 0 and not self._ready:
                            eta_s = remaining / speed_bps

            return {
                "active": active,
                "phase": self._phase,
                "stage": self._stage or None,
                "ready": self._ready,
                "error": self._error,
                "model": self._model_id,
                "elapsed_s": round(elapsed, 1),
                "eta_s": round(eta_s, 1) if eta_s is not None else None,
                "eta_is_estimate": True,
                "percent": round(frac * 100, 1) if frac is not None else None,
                "percent_is_estimate": True,
                "idle_s": round(idle, 1),
                "bytes_total": self._bytes_total or None,
                "bytes_sent": bytes_sent,
                "bytes_is_estimate": True,
                "speed_bps": round(speed_bps, 1) if speed_bps is not None else None,
                "node_count": self._node_count,
                "remote_count": self._remote_count,
                "last_log": self._last_log or None,
            }

    def stop(self) -> None:
        self._cancelling = True
        if self._proc is None:
            with self._lock:
                self._phase = "idle"
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        logger.info("coordinator_stopped", model=self._model_id)
        self._proc = None
        with self._lock:
            self._model_id = None
            self._ready = False
            self._error = None
            self._phase = "stopped"
            self._stage = ""
            self._progress_frac = None
            self._transfer_started_at = 0.0
