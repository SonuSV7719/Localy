"""
Device pooling API routes (Phase 3).

    GET  /pool/status          — current pool + coordinator state
    POST /pool/join            — add a worker (manual host:port)
    POST /pool/leave           — remove a worker
    GET  /pool/plan/{model}    — shard plan for a model across the pool
    GET  /pool/fit/{model}     — pool-fit advisor (does it fit with current pool?)
    POST /pool/load            — load a model split across the pool
    POST /pool/unload          — stop pooled inference
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from localy.core.config import Settings, get_settings
from localy.core.dependencies import verify_api_key
from localy.schemas.pool import (
    JoinRequest,
    LeaveRequest,
    PoolLoadRequest,
    PoolNodeResponse,
    PoolStatusResponse,
    ShardPlanResponse,
)
from localy.services.pool_service import get_pool_service

pool_router = APIRouter(prefix="/pool", tags=["Pooling (Phase 3)"])


@pool_router.get("/status", response_model=PoolStatusResponse, dependencies=[Depends(verify_api_key)])
async def pool_status(settings: Settings = Depends(get_settings)) -> PoolStatusResponse:
    """Return the current pool membership and coordinator state."""
    return PoolStatusResponse(**get_pool_service(settings).status())


@pool_router.post("/join", response_model=PoolNodeResponse, dependencies=[Depends(verify_api_key)])
async def pool_join(req: JoinRequest, settings: Settings = Depends(get_settings)) -> PoolNodeResponse:
    """Add a remote worker to the pool."""
    budget_bytes = req.budget_mib * 1024 * 1024 if req.budget_mib else None
    node = get_pool_service(settings).join(
        host=req.host, port=req.port, label=req.label, budget_bytes=budget_bytes
    )
    return PoolNodeResponse(
        node_id=node.node_id,
        address=node.address,
        is_local=node.is_local,
        label=node.label,
        budget_gb=round(node.budget_gb, 2),
    )


@pool_router.post("/leave", dependencies=[Depends(verify_api_key)])
async def pool_leave(req: LeaveRequest, settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    """Remove a worker from the pool."""
    return {"removed": get_pool_service(settings).leave(req.node_id)}


@pool_router.get("/discover", dependencies=[Depends(verify_api_key)])
async def pool_discover(
    auto_join: bool = False, settings: Settings = Depends(get_settings)
) -> list[dict]:
    """List pool workers advertised on the LAN via mDNS (optionally auto-join them)."""
    return get_pool_service(settings).discover(auto_join=auto_join)


@pool_router.get(
    "/plan/{model_id:path}",
    response_model=ShardPlanResponse,
    dependencies=[Depends(verify_api_key)],
)
async def pool_plan(model_id: str, settings: Settings = Depends(get_settings)) -> ShardPlanResponse:
    """Compute how a model would be split across the current pool."""
    plan = get_pool_service(settings).plan_for_model(model_id)
    return ShardPlanResponse(**plan.to_dict())


@pool_router.get(
    "/fit/{model_id:path}",
    response_model=ShardPlanResponse,
    dependencies=[Depends(verify_api_key)],
)
async def pool_fit(model_id: str, settings: Settings = Depends(get_settings)) -> ShardPlanResponse:
    """Pool-fit advisor: same as plan, framed as a fit check for the UI."""
    plan = get_pool_service(settings).plan_for_model(model_id)
    return ShardPlanResponse(**plan.to_dict())


@pool_router.post("/load", response_model=ShardPlanResponse, dependencies=[Depends(verify_api_key)])
async def pool_load(req: PoolLoadRequest, settings: Settings = Depends(get_settings)) -> ShardPlanResponse:
    """Load a model split across the pool (spawns the coordinator llama-server)."""
    plan = get_pool_service(settings).load_pooled(req.model, n_ctx=req.ctx)
    return ShardPlanResponse(**plan.to_dict())


@pool_router.post("/unload", dependencies=[Depends(verify_api_key)])
async def pool_unload(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    """Stop pooled inference."""
    get_pool_service(settings).unload_pooled()
    return {"status": "stopped"}
