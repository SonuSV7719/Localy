"""
In-memory registry of pool nodes with heartbeat tracking.

Nodes are added by manual join (Stage 1) or mDNS discovery (Stage 2). A node's
``last_seen`` is refreshed by the coordinator's active heartbeat (a periodic TCP
liveness probe to the worker's rpc port) — NOT only when it is (re)joined. Nodes
not seen within ``POOL_STALE_THRESHOLD_SECONDS`` are pruned so the shard planner
never counts a device that has dropped off the network.

Thread-safety: this registry is read/written from the FastAPI threadpool
(``asyncio.to_thread``) *and* the background heartbeat thread, so every mutation
and read is guarded by a re-entrant lock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from localy.core.constants import POOL_STALE_THRESHOLD_SECONDS
from localy.pooling.shard_planner import PoolNode


@dataclass
class TrackedNode:
    node: PoolNode
    last_seen: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_seen = time.time()

    def is_stale(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return (now - self.last_seen) > POOL_STALE_THRESHOLD_SECONDS


class PoolState:
    """Tracks the local node plus all known remote worker nodes."""

    def __init__(self) -> None:
        self._local: PoolNode | None = None
        self._remote: dict[str, TrackedNode] = {}
        self._lock = threading.RLock()

    # --- local node ---
    def set_local(self, node: PoolNode) -> None:
        node.is_local = True
        with self._lock:
            self._local = node

    @property
    def local(self) -> PoolNode | None:
        return self._local

    # --- remote nodes ---
    def upsert(self, node: PoolNode) -> None:
        """Add or refresh a remote node's heartbeat."""
        node.is_local = False
        with self._lock:
            existing = self._remote.get(node.node_id)
            if existing:
                existing.node = node
                existing.touch()
            else:
                self._remote[node.node_id] = TrackedNode(node=node)

    def touch(self, node_id: str) -> bool:
        """Refresh a node's heartbeat without replacing its metadata.

        Returns True if the node was present (and refreshed). Used by the
        liveness heartbeat, which knows a node is reachable but has no reason to
        rebuild its ``PoolNode``.
        """
        with self._lock:
            tn = self._remote.get(node_id)
            if tn is None:
                return False
            tn.touch()
            return True

    def remove(self, node_id: str) -> bool:
        with self._lock:
            return self._remote.pop(node_id, None) is not None

    def is_live(self, node_id: str) -> bool:
        """Whether a remote node is currently reachable in the live pool."""
        self.prune_stale()
        with self._lock:
            return node_id in self._remote

    def prune_stale(self) -> list[str]:
        """Drop nodes not seen recently. Returns the removed node ids."""
        now = time.time()
        with self._lock:
            stale = [nid for nid, tn in self._remote.items() if tn.is_stale(now)]
            for nid in stale:
                del self._remote[nid]
            return stale

    def remote_nodes(self) -> list[PoolNode]:
        self.prune_stale()
        with self._lock:
            return [tn.node for tn in self._remote.values()]

    def all_nodes(self) -> list[PoolNode]:
        """Local node first (matching llama-server device order), then remotes."""
        nodes: list[PoolNode] = []
        if self._local is not None:
            nodes.append(self._local)
        nodes.extend(self.remote_nodes())
        return nodes

    def has_remote(self) -> bool:
        return len(self.remote_nodes()) > 0
