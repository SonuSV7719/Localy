"""
Pool service — orchestration facade for Phase 3 device pooling.

Ties together node tracking, shard planning, and the worker/coordinator
subprocesses. Used by both the pool API routes and the `localy pool` CLI.

Solo inference is never touched here: pooled mode is only engaged explicitly
for a model that doesn't fit locally and has remote workers available.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import httpx

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
        self._events: deque[dict] = deque(maxlen=250)

        # Roster of workers the user has *intentionally* joined (manually or via
        # auto-join). This is the source of truth the heartbeat probes — a member
        # that briefly drops off (phone screen-off, WiFi power-save) stays in the
        # roster and is automatically re-added to the live pool the moment it's
        # reachable again, instead of being lost forever after one stale prune.
        self._members: dict[str, PoolNode] = {}
        self._members_lock = threading.Lock()
        self._discovery_lock = threading.Lock()

        self._init_local_node()
        self._event("pool_initialized", "Coordinator is ready")

        # Active liveness heartbeat: keeps reachable workers from being pruned
        # and auto-rejoins ones that come back. Started here so it runs for the
        # whole process lifetime (the service is a singleton).
        self._hb_stop = threading.Event()
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop, name="pool-heartbeat", daemon=True
        )
        self._heartbeat.start()

    # --- worker role (share THIS device to others' pools) ---
    def _event(self, kind: str, message: str, **details: object) -> None:
        self._events.appendleft({"at": time.time(), "kind": kind, "message": message, "details": details})
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
        self._event("local_worker_started", "This device started sharing", address=self._worker.address)
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
        self._event("local_worker_stopped", "This device stopped sharing")
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
        metrics_port: int | None = None,
    ) -> PoolNode:
        """Manually add a remote worker to the pool (Stage 1)."""
        node_id = f"{host}:{port}"
        if not self._probe_worker(host, port, metrics_port, POOL_HEARTBEAT_PROBE_TIMEOUT_SECONDS):
            raise PoolingError(
                f"Cannot reach worker at {node_id}. Make sure sharing is on, "
                "the device is awake, and both devices are on the same WiFi/hotspot."
            )
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
            metrics_port=metrics_port,
        )
        self._state.upsert(node)
        # Remember it as a member so the heartbeat keeps it alive / auto-rejoins.
        with self._members_lock:
            self._members[node_id] = node
        logger.info("pool_node_joined", address=node.address, budget_gb=round(node.budget_gb, 2))
        self._event("worker_joined", f"{node.label} joined the pool", address=node.address, budget_gb=round(node.budget_gb, 2))
        return node

    def leave(self, node_id: str) -> bool:
        # Drop from the roster first so the heartbeat won't re-add it.
        with self._members_lock:
            self._members.pop(node_id, None)
        removed = self._state.remove(node_id)
        if removed:
            self._event("worker_left", f"{node_id} left the pool")
        return removed

    # --- liveness heartbeat ---
    @staticmethod
    def _probe_worker(host: str, port: int, metrics_port: int | None, timeout: float) -> bool:
        """True if the worker responds without poisoning the RPC socket.

        llama.cpp RPC requires the first bytes on a connection to be an RPC
        HELLO. A bare TCP connect/close can occupy the worker's tiny listen
        backlog and make the next real coordinator handshake time out. Android
        workers expose a separate HTTP metrics port, so use that whenever
        available; otherwise perform a proper RPC protocol preflight.
        """
        if metrics_port:
            try:
                response = httpx.get(f"http://{host}:{metrics_port}/metrics", timeout=timeout)
                if response.status_code < 400:
                    data = response.json()
                    return bool(data.get("running", True))
            except Exception:
                return False

        try:
            Coordinator._verify_rpc_workers([f"{host}:{port}"])
            return True
        except Exception:
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
                    if self._probe_worker(
                        node.host,
                        node.port,
                        node.metrics_port,
                        POOL_HEARTBEAT_PROBE_TIMEOUT_SECONDS,
                    ):
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
                    metrics_port=w.metrics_port,
                )
            results.append(
                {
                    "node_id": w.node_id,
                    "host": w.host,
                    "port": w.port,
                    "label": w.label,
                    "budget_gb": round(w.budget_bytes / (1024**3), 2) if w.budget_bytes else None,
                    "metrics_available": w.metrics_port is not None,
                    "metrics_port": w.metrics_port,
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
        self._event("model_load_started", f"Coordinating {model_id}", model=model_id, devices=len(plan.nodes))
        self._coordinator.start(model_id, model_path, plan, n_ctx=n_ctx)
        return plan

    def unload_pooled(self) -> None:
        self._event("model_unloaded", "Pooled model stopped", model=self._coordinator.model_id)
        self._coordinator.stop()

    def operations(self) -> dict:
        """Live topology plus a bounded coordination timeline for the UI."""
        status = self.status()
        model = status["active_model"]
        plan_dict = None
        if model:
            try:
                plan_dict = self.plan_for_model(model).to_dict()
            except Exception:
                pass
        shares = {
            n["node_id"]: n["layer_share_pct"]
            for n in plan_dict["nodes"]
        } if plan_dict else {}
        for node in status["nodes"]:
            node["planned_layer_share_pct"] = round(shares.get(node["node_id"], 0.0), 1)
            node["planned_model_bytes"] = int(
                (plan_dict["model_size_bytes"] if plan_dict else 0)
                * shares.get(node["node_id"], 0.0)
                / 100
            )
            node["memory_measurement"] = "planned_budget"
        return {
            "status": status,
            "events": list(self._events),
            "model_size_bytes": plan_dict["model_size_bytes"] if plan_dict else None,
        }

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
        live_nodes = self._state.all_nodes()
        live_by_id = {n.node_id: n for n in live_nodes if not n.is_local}
        with self._members_lock:
            joined_nodes = list(self._members.values())

        nodes = []
        if self._state.local is not None:
            nodes.append((self._state.local, True))
        for member in joined_nodes:
            nodes.append((live_by_id.get(member.node_id, member), member.node_id in live_by_id))

        total = sum(n.budget_bytes for n, online in nodes if online)
        online_count = sum(1 for _, online in nodes if online)
        offline_count = len(nodes) - online_count
        return {
            # "active" now means *ready and serving* — matches is_serving, so the
            # UI's 🔗 badge only shows once the pool can actually answer requests.
            "pooled_active": self._coordinator.is_ready,
            "active_model": self._coordinator.model_id,
            "proxy_url": self.proxy_url,
            "worker_running": self.worker_running,
            "node_count": len(nodes),
            "remote_count": len(joined_nodes),
            "online_count": online_count,
            "offline_count": offline_count,
            "total_budget_gb": round(total / (1024**3), 2),
            "loading": self._coordinator.progress(),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "address": n.address,
                    "is_local": n.is_local,
                    "label": n.label,
                    "budget_gb": round(n.budget_gb, 2),
                    "online": online,
                }
                for n, online in nodes
            ],
        }


# Singleton (mirrors other services' pattern).
_pool_service: PoolService | None = None


def get_pool_service(settings: Settings) -> PoolService:
    global _pool_service
    if _pool_service is None:
        _pool_service = PoolService(settings)
    return _pool_service
