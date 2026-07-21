"""
Pool service — orchestration facade for Phase 3 device pooling.

Ties together node tracking, shard planning, and the worker/coordinator
subprocesses. Used by both the pool API routes and the `localy pool` CLI.

Solo inference is never touched here: pooled mode is only engaged explicitly
for a model that doesn't fit locally and has remote workers available.
"""

from __future__ import annotations

import socket
import threading
import time

from localy.core.config import Settings
from localy.core.constants import (
    POOL_HEALTH_CHECK_INTERVAL_SECONDS,
    POOL_HEARTBEAT_PROBE_TIMEOUT_SECONDS,
)
from localy.core.exceptions import ModelNotFoundError, PoolingError
from localy.core.logging import get_logger
from localy.inference.model_manager import ModelManager
from localy.pooling.coordinator import Coordinator
from localy.pooling.discovery import WorkerAdvertiser, WorkerDiscovery, _local_ip
from localy.pooling.pool_state import PoolState
from localy.pooling.shard_planner import PoolNode, ShardPlan, plan_shards
from localy.pooling.worker import WorkerProcess, compute_local_capacity
from localy.storage.model_store import ModelStore

logger = get_logger(__name__)


class PoolService:
    """Coordinator-side pooling orchestration."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._state = PoolState()
        self._coordinator = Coordinator(settings)
        self._manager = ModelManager(settings, ModelStore(settings))
        self._discovery: WorkerDiscovery | None = None
        self._worker: WorkerProcess | None = None
        self._advertiser: WorkerAdvertiser | None = None

        # Roster of workers the user has *intentionally* joined (manually or via
        # auto-join). This is the source of truth the heartbeat probes — a member
        # that briefly drops off (phone screen-off, WiFi power-save) stays in the
        # roster and is automatically re-added to the live pool the moment it's
        # reachable again, instead of being lost forever after one stale prune.
        self._members: dict[str, PoolNode] = {}
        self._members_lock = threading.Lock()
        self._discovery_lock = threading.Lock()

        self._init_local_node()

        # Active liveness heartbeat: keeps reachable workers from being pruned
        # and auto-rejoins ones that come back. Started here so it runs for the
        # whole process lifetime (the service is a singleton).
        self._hb_stop = threading.Event()
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop, name="pool-heartbeat", daemon=True
        )
        self._heartbeat.start()

    # --- worker role (share THIS device to others' pools) ---
    @property
    def worker_running(self) -> bool:
        return self._worker is not None and self._worker.is_running

    def start_worker(self) -> dict:
        """Start sharing this device: run rpc-server + advertise over mDNS."""
        if self.worker_running:
            return {"running": True, "address": self._worker.address}  # type: ignore[union-attr]
        cap = compute_local_capacity(self._settings)
        self._worker = WorkerProcess(self._settings)
        self._worker.start()  # raises PoolingError if binaries missing / port busy
        self._advertiser = WorkerAdvertiser(
            port=self._settings.rpc_port,
            label="",
            budget_bytes=cap.offered_bytes,
            compute_score=cap.compute_score,
        )
        try:
            self._advertiser.start()
        except Exception as e:  # discovery is best-effort; worker still usable by IP
            logger.warning("advertise_failed", error=str(e))
        logger.info("worker_shared", address=self._worker.address)
        return {"running": True, "address": self._worker.address}

    def stop_worker(self) -> dict:
        # Best-effort teardown: a failure unadvertising must not prevent the
        # rpc-server from being stopped, and must never bubble a 500.
        if self._advertiser is not None:
            try:
                self._advertiser.stop()
            except Exception as e:
                logger.warning("advertiser_stop_failed", error=str(e))
            self._advertiser = None
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception as e:
                logger.warning("worker_stop_failed", error=str(e))
            self._worker = None
        return {"running": False}

    def _init_local_node(self) -> None:
        """Register this machine as the local (coordinator) node."""
        cap = compute_local_capacity(self._settings)
        self._state.set_local(
            PoolNode(
                node_id="local",
                host="local",
                port=0,
                budget_bytes=cap.offered_bytes,
                is_local=True,
                label="This device",
                compute_score=cap.compute_score,
            )
        )

    # --- membership ---
    def join(
        self,
        host: str,
        port: int,
        label: str = "",
        budget_bytes: int | None = None,
        compute_score: float = 1.0,
    ) -> PoolNode:
        """Manually add a remote worker to the pool (Stage 1)."""
        node_id = f"{host}:{port}"
        # Without discovery metadata we can't probe the remote's RAM. Assuming
        # this PC's budget badly over-estimates a phone/tablet, which then gets
        # assigned too many layers and OOM-crashes mid-serving. Use a modest,
        # safe default instead; discovery-based joins pass the real budget.
        if budget_bytes is None:
            budget_bytes = 2 * 1024 * 1024 * 1024  # 2 GB conservative default
        node = PoolNode(
            node_id=node_id,
            host=host,
            port=port,
            budget_bytes=budget_bytes,
            label=label or node_id,
            compute_score=compute_score,
        )
        self._state.upsert(node)
        # Remember it as a member so the heartbeat keeps it alive / auto-rejoins.
        with self._members_lock:
            self._members[node_id] = node
        logger.info("pool_node_joined", address=node.address, budget_gb=round(node.budget_gb, 2))
        return node

    def leave(self, node_id: str) -> bool:
        # Drop from the roster first so the heartbeat won't re-add it.
        with self._members_lock:
            self._members.pop(node_id, None)
        return self._state.remove(node_id)

    # --- liveness heartbeat ---
    @staticmethod
    def _probe(host: str, port: int, timeout: float) -> bool:
        """True if a TCP connection to host:port succeeds (worker is alive)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                return s.connect_ex((host, port)) == 0
        except OSError:
            return False

    def _heartbeat_loop(self) -> None:
        """Periodically probe every roster member and refresh live membership.

        Reachable members are (re-)added to the live pool and their heartbeat
        refreshed, so an active worker is never pruned. Unreachable members are
        left alone: they age out of the *live* view via ``prune_stale`` but stay
        in the roster, so they auto-rejoin as soon as they respond again.
        """
        # Start the mDNS browser here (off the event-loop thread) so a worker
        # that re-announces after dropping is caught promptly. Best-effort:
        # pooling works by IP + heartbeat even if zeroconf is unavailable.
        try:
            self._ensure_discovery()
        except Exception as e:
            logger.warning("discovery_autostart_failed", error=str(e))

        while not self._hb_stop.wait(POOL_HEALTH_CHECK_INTERVAL_SECONDS):
            with self._members_lock:
                members = list(self._members.items())
            for node_id, node in members:
                try:
                    if self._probe(node.host, node.port, POOL_HEARTBEAT_PROBE_TIMEOUT_SECONDS):
                        # upsert adds it back if it had aged out, or just touches it.
                        self._state.upsert(node)
                except Exception:  # pragma: no cover - probe must never crash the loop
                    pass

    def shutdown(self) -> None:
        """Stop background threads (heartbeat + discovery). Best-effort."""
        self._hb_stop.set()
        if self._discovery is not None:
            try:
                self._discovery.stop()
            except Exception:
                pass
            self._discovery = None

    # --- discovery (mDNS) ---
    def _on_discovery_change(self) -> None:
        """mDNS saw a worker (re)appear. If it's a known member, re-add it to
        the live pool immediately — a faster complement to the TCP heartbeat."""
        disc = self._discovery
        if disc is None:
            return
        try:
            for w in disc.list_workers():
                node_id = f"{w.host}:{w.port}"
                with self._members_lock:
                    member = self._members.get(node_id)
                if member is not None:
                    self._state.upsert(member)
        except Exception:  # pragma: no cover - callback must never raise into zeroconf
            pass

    def _ensure_discovery(self) -> WorkerDiscovery:
        with self._discovery_lock:
            if self._discovery is None:
                disc = WorkerDiscovery(on_change=self._on_discovery_change)
                disc.start()
                self._discovery = disc
            return self._discovery

    def discover(self, auto_join: bool = False, wait_seconds: float = 2.5) -> list[dict]:
        """List workers advertised on the LAN via mDNS. Optionally auto-join them.

        mDNS responses arrive asynchronously, so on the first scan we give the
        browser a moment to collect answers (runs in a worker thread, so this
        does not block the API event loop). Excludes this device itself.
        """
        fresh = self._discovery is None
        disc = self._ensure_discovery()
        if fresh and wait_seconds > 0:
            time.sleep(wait_seconds)

        # Don't list this machine's own advertisement (when it's sharing) as a
        # discoverable peer — match on our own LAN IP + rpc port.
        my_ip = _local_ip()
        my_port = self._settings.rpc_port

        results = []
        for w in disc.list_workers():
            if w.host == my_ip and w.port == my_port:
                continue  # that's us
            if auto_join:
                self.join(
                    w.host,
                    w.port,
                    label=w.label,
                    budget_bytes=w.budget_bytes or None,
                    compute_score=w.compute_score,
                )
            results.append(
                {
                    "node_id": w.node_id,
                    "host": w.host,
                    "port": w.port,
                    "label": w.label,
                    "budget_gb": round(w.budget_bytes / (1024**3), 2) if w.budget_bytes else None,
                }
            )
        return results

    # --- planning ---
    def _model_size_bytes(self, model_id: str) -> int:
        # Prefer the downloaded file's real size; otherwise use the registry
        # variant's advertised size so "check fit" works BEFORE downloading.
        try:
            path = self._manager.get_local_model_path(model_id)
            return path.stat().st_size
        except Exception:
            _entry, variant = self._manager.registry.resolve(model_id)
            if variant.file_size_bytes:
                return variant.file_size_bytes
            raise PoolingError(
                f"Can't determine the size of '{model_id}' — download it first to check fit."
            )

    def plan_for_model(self, model_id: str) -> ShardPlan:
        """Compute the shard plan for a model across the current pool."""
        size = self._model_size_bytes(model_id)
        return plan_shards(self._state.all_nodes(), size)

    # --- lifecycle ---
    def load_pooled(self, model_id: str, n_ctx: int = 4096) -> ShardPlan:
        """Load a model split across the pool. Raises if it doesn't fit."""
        if not self._state.has_remote():
            raise PoolingError(
                "No remote workers in the pool. Join at least one with "
                "`localy pool join <host:port>` (or start `localy worker` on another device)."
            )
        plan = self.plan_for_model(model_id)
        if not plan.fits:
            raise PoolingError(f"Model does not fit across the pool. {plan.reason}")

        model_path = self._manager.get_local_model_path(model_id)
        self._coordinator.start(model_id, model_path, plan, n_ctx=n_ctx)
        return plan

    def unload_pooled(self) -> None:
        self._coordinator.stop()

    # --- status ---
    @property
    def proxy_url(self) -> str | None:
        return self._coordinator.proxy_url if self._coordinator.is_running else None

    def is_serving(self, model_id: str) -> bool:
        """True if a pooled coordinator is *ready* and serving this model.

        Gated on readiness so chat doesn't proxy to a coordinator that is still
        streaming weights to workers (it would fail); until ready, requests fall
        through to the solo path.
        """
        return self._coordinator.is_ready and self._coordinator.model_id == model_id

    def serving_url(self) -> str | None:
        """Base URL of the active pooled coordinator, if any."""
        return self._coordinator.proxy_url if self._coordinator.is_running else None

    def status(self) -> dict:
        nodes = self._state.all_nodes()
        total = sum(n.budget_bytes for n in nodes)
        return {
            # "active" now means *ready and serving* — matches is_serving, so the
            # UI's 🔗 badge only shows once the pool can actually answer requests.
            "pooled_active": self._coordinator.is_ready,
            "active_model": self._coordinator.model_id,
            "proxy_url": self.proxy_url,
            "worker_running": self.worker_running,
            "node_count": len(nodes),
            "remote_count": len(self._state.remote_nodes()),
            "total_budget_gb": round(total / (1024**3), 2),
            "loading": self._coordinator.progress(),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "address": n.address,
                    "is_local": n.is_local,
                    "label": n.label,
                    "budget_gb": round(n.budget_gb, 2),
                }
                for n in nodes
            ],
        }


# Singleton (mirrors other services' pattern).
_pool_service: PoolService | None = None


def get_pool_service(settings: Settings) -> PoolService:
    global _pool_service
    if _pool_service is None:
        _pool_service = PoolService(settings)
    return _pool_service
