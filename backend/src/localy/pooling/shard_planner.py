"""
Shard planner — decide whether a model fits across a pool of devices and how
to weight its layers between them.

llama.cpp's RPC backend splits a model's layers across devices according to
`--tensor-split` proportions. This module computes those proportions from each
device's usable memory budget (from the hardware probe), and decides whether
the combined pool can actually hold the model.

Pooling is about *capacity*, not speed: this planner answers "can we run it and
how should the layers be divided", not "will it be fast".
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A model needs its weight file plus KV cache + compute buffers in memory.
# Rough multiplier over the raw GGUF size to cover that overhead per pool.
_MODEL_OVERHEAD_FACTOR = 1.20


@dataclass
class PoolNode:
    """A device offering memory/compute to the pool."""

    node_id: str
    host: str
    port: int
    budget_bytes: int  # usable memory this node offers (safe_model_budget-derived)
    is_local: bool = False  # True for the coordinator's own machine
    label: str = ""
    compute_score: float = 1.0  # relative inference speed (threads x SIMD, or tok/s)
    metrics_port: int | None = None  # optional worker telemetry HTTP port

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def budget_gb(self) -> float:
        return self.budget_bytes / (1024**3)


@dataclass
class ShardPlan:
    """Result of planning a model across a pool."""

    fits: bool
    model_size_bytes: int
    required_bytes: int
    total_budget_bytes: int
    nodes: list[PoolNode]
    tensor_split: list[float]  # normalized weight per node, aligned with `nodes`
    reason: str
    recommendations: list[str] = field(default_factory=list)

    @property
    def rpc_endpoints(self) -> list[str]:
        """Addresses of the remote (non-local) nodes, for llama-server --rpc."""
        return [n.address for n in self.nodes if not n.is_local]

    def to_dict(self) -> dict:
        return {
            "fits": self.fits,
            "model_size_bytes": self.model_size_bytes,
            "required_bytes": self.required_bytes,
            "total_budget_bytes": self.total_budget_bytes,
            "total_budget_gb": round(self.total_budget_bytes / (1024**3), 2),
            "tensor_split": [round(w, 4) for w in self.tensor_split],
            "reason": self.reason,
            "recommendations": self.recommendations,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "address": n.address,
                    "is_local": n.is_local,
                    "label": n.label,
                    "budget_gb": round(n.budget_gb, 2),
                    "layer_share_pct": round(w * 100, 1),
                }
                for n, w in zip(self.nodes, self.tensor_split)
            ],
        }


def _water_fill(caps: list[float], weights: list[float], total: float) -> list[float]:
    """Distribute `total` across items proportional to `weights`, capped by `caps`.

    Water-filling: allocate by weight; when an item hits its cap, freeze it and
    redistribute the remainder among the rest. Guarantees alloc[i] <= caps[i] and
    sum(alloc) == min(total, sum(caps)). With equal weights this reduces to
    RAM-proportional; with unequal weights, faster devices get more (up to RAM).
    """
    n = len(caps)
    alloc = [0.0] * n
    active = [i for i in range(n) if caps[i] > 0]
    remaining = min(total, sum(caps))
    while remaining > 1.0 and active:
        wsum = sum(weights[i] for i in active)
        if wsum <= 0:
            break
        capped_now = []
        added_total = 0.0
        for i in list(active):
            give = remaining * (weights[i] / wsum)
            room = caps[i] - alloc[i]
            if give >= room:
                alloc[i] = caps[i]
                added_total += room
                capped_now.append(i)
            else:
                alloc[i] += give
                added_total += give
        remaining -= added_total
        if capped_now:
            active = [i for i in active if i not in capped_now]
        else:
            break  # everyone within caps — done
    return alloc


def plan_shards(nodes: list[PoolNode], model_size_bytes: int) -> ShardPlan:
    """Plan how to split `model_size_bytes` of weights across `nodes`.

    Nodes should be ordered with the local coordinator node first (if it
    participates), matching the device order llama-server will enumerate.
    """
    if not nodes:
        return ShardPlan(
            fits=False,
            model_size_bytes=model_size_bytes,
            required_bytes=int(model_size_bytes * _MODEL_OVERHEAD_FACTOR),
            total_budget_bytes=0,
            nodes=[],
            tensor_split=[],
            reason="No devices in the pool. Add at least one worker to pool.",
            recommendations=["Start a worker on another device with `localy worker`."],
        )

    total_budget = sum(n.budget_bytes for n in nodes)
    required = int(model_size_bytes * _MODEL_OVERHEAD_FACTOR)
    fits = total_budget >= required and total_budget > 0

    # Compute-aware water-filling: give faster devices MORE layers (so a slow
    # node doesn't bottleneck the pipeline), but never assign a device more than
    # its RAM can hold. Falls back to pure RAM-proportional when all devices
    # report equal compute. See _water_fill.
    caps = [max(0, n.budget_bytes) for n in nodes]
    weights = [max(1e-6, n.compute_score) for n in nodes]
    to_place = min(required, total_budget) if total_budget > 0 else 0
    alloc = _water_fill(caps, weights, to_place)
    placed = sum(alloc)
    if placed > 0:
        tensor_split = [a / placed for a in alloc]
    else:
        tensor_split = [1.0 / len(nodes)] * len(nodes)

    n_remote = sum(1 for n in nodes if not n.is_local)
    budget_gb = total_budget / (1024**3)
    model_gb = model_size_bytes / (1024**3)

    recommendations: list[str] = []
    if fits:
        reason = (
            f"Model (~{model_gb:.1f} GB) fits across {len(nodes)} device(s) "
            f"(~{budget_gb:.1f} GB pooled). Layers weighted by each device's speed, "
            f"capped by its memory."
        )
        if n_remote > 0:
            recommendations.append(
                "Pooling adds per-token network latency — a model that fits on one "
                "device alone will be faster solo."
            )
    else:
        short_gb = (required - total_budget) / (1024**3)
        reason = (
            f"Model (~{model_gb:.1f} GB + overhead) needs ~{required / (1024**3):.1f} GB "
            f"but the pool only offers ~{budget_gb:.1f} GB (short ~{short_gb:.1f} GB)."
        )
        recommendations.append("Add another device to the pool, or")
        recommendations.append("Choose a smaller model or a lower quantization (e.g. Q4_K_M).")

    return ShardPlan(
        fits=fits,
        model_size_bytes=model_size_bytes,
        required_bytes=required,
        total_budget_bytes=total_budget,
        nodes=nodes,
        tensor_split=tensor_split,
        reason=reason,
        recommendations=recommendations,
    )
