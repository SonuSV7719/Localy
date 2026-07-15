"""
Pool service — orchestration facade for Phase 3 device pooling.

Ties together node tracking, shard planning, and the worker/coordinator
subprocesses. Used by both the pool API routes and the `localy pool` CLI.

Solo inference is never touched here: pooled mode is only engaged explicitly
for a model that doesn't fit locally and has remote workers available.
"""

from __future__ import annotations

import time

from localy.core.config import Settings
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
        self._init_local_node()

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
        # Without discovery metadata we can't probe the remote's RAM, so fall
        # back to this device's offered budget as a conservative estimate.
        if budget_bytes is None:
            budget_bytes = compute_local_capacity(self._settings).offered_bytes
        node = PoolNode(
            node_id=node_id,
            host=host,
            port=port,
            budget_bytes=budget_bytes,
            label=label or node_id,
            compute_score=compute_score,
        )
        self._state.upsert(node)
        logger.info("pool_node_joined", address=node.address, budget_gb=round(node.budget_gb, 2))
        return node

    def leave(self, node_id: str) -> bool:
        return self._state.remove(node_id)

    # --- discovery (mDNS) ---
    def _ensure_discovery(self) -> WorkerDiscovery:
        if self._discovery is None:
            self._discovery = WorkerDiscovery()
            self._discovery.start()
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
        """True if a pooled coordinator is actively serving this model."""
        return self._coordinator.is_running and self._coordinator.model_id == model_id

    def serving_url(self) -> str | None:
        """Base URL of the active pooled coordinator, if any."""
        return self._coordinator.proxy_url if self._coordinator.is_running else None

    def status(self) -> dict:
        nodes = self._state.all_nodes()
        total = sum(n.budget_bytes for n in nodes)
        return {
            "pooled_active": self._coordinator.is_running,
            "active_model": self._coordinator.model_id,
            "proxy_url": self.proxy_url,
            "worker_running": self.worker_running,
            "node_count": len(nodes),
            "remote_count": len(self._state.remote_nodes()),
            "total_budget_gb": round(total / (1024**3), 2),
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
