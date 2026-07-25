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
import socket
import struct
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
_RPC_PREFLIGHT_TIMEOUT_SECONDS = 15.0
_MIN_OBSERVED_TRANSFER_BYTES = 1024 * 1024


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
        self._bytes_total = 0         # planned remote weight allocation
        self._metric_endpoints: list[str] = []
        self._metric_baselines: dict[str, int] = {}
        self._metric_samples: deque[tuple[float, int]] = deque(maxlen=30)
        self._observed_bytes: int | None = None
        self._last_transfer_at = 0.0
        self._metrics_stop = threading.Event()
        self._metrics_reader: threading.Thread | None = None
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
        self._verify_rpc_workers(endpoints)

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
            "--fit", "on",
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
            self._bytes_total = bytes_total
            self._metric_endpoints = [
                f"http://{node.host}:{node.metrics_port}/metrics"
                for node in plan.nodes
                if not node.is_local and node.metrics_port
            ]
            self._metric_baselines = {}
            self._metric_samples.clear()
            self._observed_bytes = None
            self._last_transfer_at = 0.0
            self._metrics_stop.clear()
            self._node_count = len(plan.nodes)
            self._remote_count = len(endpoints)
            self._last_log = ""
            self._log_tail.clear()

        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()
        if self._metric_endpoints:
            self._metrics_reader = threading.Thread(target=self._read_worker_metrics, daemon=True)
            self._metrics_reader.start()
        self._monitor = threading.Thread(
            target=self._await_ready, args=(ready_timeout,), daemon=True
        )
        self._monitor.start()

    @staticmethod
    def _verify_rpc_workers(endpoints: list[str]) -> None:
        """Fail fast when a worker accepts TCP but cannot speak llama RPC.

        A TCP probe alone is insufficient: a stale Android RPC cache can accept
        a connection then block before its HELLO response. This sends the
        llama.cpp RPC HELLO, device-count, and memory commands directly, so it
        exercises the exact transport without launching a second server process.
        """
        for endpoint in endpoints:
            try:
                host, port_text = endpoint.rsplit(":", 1)
                with socket.create_connection((host, int(port_text)), timeout=_RPC_PREFLIGHT_TIMEOUT_SECONDS) as conn:
                    conn.settimeout(_RPC_PREFLIGHT_TIMEOUT_SECONDS)
                    # RPC_CMD_HELLO=14, request size=24, zero transport caps.
                    conn.sendall(b"\x0e" + struct.pack("<Q", 24) + bytes(24))
                    response = Coordinator._recv_rpc_message(conn)
                    if len(response) != 28 or response[0] != 4:
                        raise ValueError("unexpected HELLO response")

                    # RPC_CMD_DEVICE_COUNT=15 with an empty request.
                    conn.sendall(b"\x0f" + struct.pack("<Q", 0))
                    device_count = Coordinator._recv_rpc_message(conn)
                    if len(device_count) != 4 or struct.unpack("<I", device_count)[0] < 1:
                        raise ValueError("worker reported no usable devices")

                    # RPC_CMD_GET_DEVICE_MEMORY=11 for device 0.
                    conn.sendall(b"\x0b" + struct.pack("<Q", 4) + struct.pack("<I", 0))
                    memory = Coordinator._recv_rpc_message(conn)
                    if len(memory) != 16 or struct.unpack("<Q", memory[8:])[0] <= 0:
                        raise ValueError("worker reported invalid device memory")
            except (OSError, ValueError, struct.error) as e:
                raise ClusterFormationError(
                    f"Worker {endpoint} failed the RPC handshake: {e}. "
                    "Restart sharing on that device and try again."
                ) from e

    @staticmethod
    def _recv_rpc_message(conn: socket.socket) -> bytes:
        size_raw = Coordinator._recv_exact(conn, 8)
        size = struct.unpack("<Q", size_raw)[0]
        if size > 1024 * 1024:
            raise ValueError(f"invalid RPC response size {size}")
        return Coordinator._recv_exact(conn, size)

    @staticmethod
    def _recv_exact(conn: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                raise OSError("connection closed before the RPC response")
            data.extend(chunk)
        return bytes(data)

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
        fatal_error: str | None = None
        with self._lock:
            self._last_log = line[:300]
            self._last_log_at = time.time()
            self._log_tail.append(line[:300])

            if self._phase == "starting":
                self._phase = "loading"

            # llama-server can otherwise continue in local-only mode when a
            # remote endpoint drops. Never present that as a pooled load.
            if "failed to connect to" in low or "remote rpc server crashed" in low:
                fatal_error = "Lost the RPC worker while starting the pooled model."
            elif (
                "failed to fit params" in low
                or "failed to allocate" in low
                or "out of memory" in low
                or "vk::outofdevicememory" in low
            ):
                fatal_error = (
                    "llama.cpp could not fit the pooled model into the available "
                    "device memory. Try a smaller quant/context, remove low-memory "
                    "workers, or close other GPU-heavy apps before loading again."
                )

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
        if fatal_error:
            self._fail(fatal_error)

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

    def _read_worker_metrics(self) -> None:
        """Collect Android worker UID traffic counters while model layers load.

        llama.cpp exposes no RPC byte counter. Localy Android workers provide a
        tiny read-only endpoint backed by Android's per-UID traffic accounting,
        which gives the UI observed network transfer rather than a phase guess.
        """
        while not self._metrics_stop.wait(0.75):
            if not self.is_running:
                return
            values: dict[str, int] = {}
            for endpoint in self._metric_endpoints:
                try:
                    response = httpx.get(endpoint, timeout=0.6)
                    value = response.json().get("rx_bytes")
                    if response.status_code == 200 and isinstance(value, int) and value >= 0:
                        values[endpoint] = value
                except (httpx.HTTPError, ValueError, TypeError):
                    continue
            if len(values) != len(self._metric_endpoints):
                continue
            now = time.time()
            with self._lock:
                for endpoint, value in values.items():
                    self._metric_baselines.setdefault(endpoint, value)
                observed = sum(
                    max(0, values[endpoint] - self._metric_baselines[endpoint])
                    for endpoint in self._metric_endpoints
                )
                if self._observed_bytes is None or observed > self._observed_bytes:
                    self._last_transfer_at = now
                self._observed_bytes = observed
                self._metric_samples.append((now, observed))

    def _fail(self, message: str) -> None:
        with self._lock:
            tail = "\n".join(list(self._log_tail)[-20:])
            self._error = f"{message}\n{tail}".strip()
            self._phase = "error"
            self._ready = False
        logger.warning("coordinator_failed", model=self._model_id, error=message)
        self._metrics_stop.set()
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

            # Loader phases are useful status only. They never become transfer
            # counters when worker telemetry exists: llama.cpp does not expose
            # byte-exact RPC progress.
            raw_observed_bytes = self._observed_bytes
            bytes_sent = raw_observed_bytes if (
                raw_observed_bytes is not None
                and raw_observed_bytes >= _MIN_OBSERVED_TRANSFER_BYTES
            ) else None
            if bytes_sent is not None and self._bytes_total:
                bytes_sent = min(bytes_sent, self._bytes_total)
            eta_s: float | None = None
            speed_bps: float | None = None
            bytes_is_estimate = bytes_sent is None
            transfer_measurement = "observed_network" if bytes_sent is not None else "not_available"
            if bytes_sent is not None and len(self._metric_samples) >= 2:
                started_at, started_bytes = self._metric_samples[0]
                ended_at, ended_bytes = self._metric_samples[-1]
                window = ended_at - started_at
                if window >= 1.0 and ended_bytes > started_bytes:
                    speed_bps = (ended_bytes - started_bytes) / window
                    remaining = max(0, self._bytes_total - bytes_sent)
                    if speed_bps > 0 and not self._ready:
                        eta_s = remaining / speed_bps
            elif self._bytes_total and frac is not None:
                transfer_frac = (frac - _TRANSFER_BAND_START) / (_TRANSFER_BAND_END - _TRANSFER_BAND_START)
                transfer_frac = max(0.0, min(1.0, transfer_frac))
                bytes_sent = int(self._bytes_total * transfer_frac)
                transfer_measurement = "estimated_from_loader"
                if elapsed > 1.0 and bytes_sent > 0:
                    speed_bps = bytes_sent / elapsed
                    remaining = max(0, self._bytes_total - bytes_sent)
                    if speed_bps > 0 and not self._ready:
                        eta_s = remaining / speed_bps
            transfer_idle = None
            if self._observed_bytes is not None:
                transfer_idle = max(0.0, time.time() - self._last_transfer_at) if self._last_transfer_at else elapsed

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
                "bytes_is_estimate": bytes_is_estimate,
                "speed_bps": round(speed_bps, 1) if speed_bps is not None else None,
                "transfer_measurement": transfer_measurement,
                "transfer_idle_s": round(transfer_idle, 1) if transfer_idle is not None else None,
                "node_count": self._node_count,
                "remote_count": self._remote_count,
                "last_log": self._last_log or None,
            }

    def stop(self) -> None:
        self._cancelling = True
        self._metrics_stop.set()
        if self._proc is None:
            self._reset_state_after_stop("idle")
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        logger.info("coordinator_stopped", model=self._model_id)
        self._proc = None
        self._reset_state_after_stop("stopped")

    def _reset_state_after_stop(self, phase: str) -> None:
        with self._lock:
            self._model_id = None
            self._ready = False
            self._error = None
            self._phase = phase
            self._stage = ""
            self._progress_frac = None
            self._bytes_total = 0
            self._metric_endpoints = []
            self._metric_baselines = {}
            self._metric_samples.clear()
            self._observed_bytes = None
            self._last_transfer_at = 0.0
            self._node_count = 0
            self._remote_count = 0
            self._last_log = ""
            self._log_tail.clear()
