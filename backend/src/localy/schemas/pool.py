"""
API schemas for device pooling (Phase 3). Mirrors the style of schemas/hardware.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PoolNodeResponse(BaseModel):
    node_id: str
    address: str
    is_local: bool
    label: str
    budget_gb: float


class PoolLoadProgress(BaseModel):
    active: bool = False          # a load is in progress right now
    phase: str = "idle"           # idle | starting | loading | ready | error | stopped
    ready: bool = False
    error: str | None = None
    model: str | None = None
    elapsed_s: float = 0.0
    eta_s: float | None = None
    percent: float | None = None  # 0..100 if the loader reports it
    bytes_total: int | None = None
    bytes_sent: int | None = None
    node_count: int = 0
    remote_count: int = 0
    last_log: str | None = None


class PoolStatusResponse(BaseModel):
    pooled_active: bool
    active_model: str | None = None
    proxy_url: str | None = None
    worker_running: bool = False
    node_count: int
    remote_count: int
    total_budget_gb: float
    loading: PoolLoadProgress | None = None
    nodes: list[PoolNodeResponse]


class ShardPlanNode(BaseModel):
    node_id: str
    address: str
    is_local: bool
    label: str
    budget_gb: float
    layer_share_pct: float


class ShardPlanResponse(BaseModel):
    fits: bool
    model_size_bytes: int
    required_bytes: int
    total_budget_bytes: int
    total_budget_gb: float
    tensor_split: list[float]
    reason: str
    recommendations: list[str]
    nodes: list[ShardPlanNode]


class JoinRequest(BaseModel):
    host: str = Field(..., description="Worker host/IP.")
    port: int = Field(..., ge=1, le=65535, description="Worker rpc-server port.")
    label: str = Field("", description="Friendly label for the device.")
    budget_mib: int | None = Field(
        None, description="Memory the worker offers, in MiB (optional)."
    )


class LeaveRequest(BaseModel):
    node_id: str


class PoolLoadRequest(BaseModel):
    model: str = Field(..., description="Model id to load across the pool.")
    ctx: int = Field(4096, ge=512, le=131072, description="Context length.")
