"""
System monitoring and diagnostics API router.

Exposes endpoints for health checking, hardware probing, and benchmark runs.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, status

from localy.core.config import get_settings
from localy.core.dependencies import (
    get_hardware_report,
    get_model_service,
    verify_api_key,
)
from localy.schemas.hardware import HardwareReportResponse, FitAssessmentResponse
from localy.services.model_service import ModelService
from localy.services.hardware_service import HardwareService
from localy.services.benchmark_service import BenchmarkService

system_router = APIRouter(tags=["System & Monitoring"])


@system_router.get("/health", response_model=dict[str, str])
async def health_check() -> dict[str, str]:
    """Basic service health check (liveness)."""
    return {"status": "ok"}


@system_router.get("/ready", response_model=dict[str, Any])
async def readiness_check(
    model_service: ModelService = Depends(get_model_service),
) -> dict[str, Any]:
    """Service readiness check (verifies hardware probed and returns active model status)."""
    active_model = await model_service.get_active_model()
    return {
        "status": "ready",
        "model_loaded": active_model is not None,
        "active_model": active_model.model_id if active_model else None,
    }


@system_router.get(
    "/system/hardware",
    response_model=HardwareReportResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_hardware(
    settings = Depends(get_settings),
) -> Any:
    """Run full hardware probe and return detailed report."""
    hw_service = HardwareService(settings)
    return hw_service.get_hardware_report()


@system_router.get(
    "/system/hardware/fit/{model_id:path}",
    response_model=FitAssessmentResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_model_fit(
    model_id: str,
    context: int | None = None,
    settings = Depends(get_settings),
) -> Any:
    """Assess whether a specific model fits on the current hardware."""
    hw_service = HardwareService(settings)
    return hw_service.get_fit_assessment(model_id, context)


@system_router.get(
    "/system/models",
    dependencies=[Depends(verify_api_key)],
)
async def get_system_models(
    dynamic: bool = True,
    model_service: ModelService = Depends(get_model_service),
) -> list[dict[str, Any]]:
    """Full catalog with per-model quantization variants fetched live from HF (cached)."""
    import asyncio

    # Variant fetch may hit the network on a cache miss — run off the event loop.
    return await asyncio.to_thread(model_service.list_models, dynamic)


@system_router.get(
    "/system/catalog/search",
    dependencies=[Depends(verify_api_key)],
)
async def search_catalog(
    q: str = "",
    model_service: ModelService = Depends(get_model_service),
) -> list[dict[str, Any]]:
    """Search Hugging Face for GGUF models to add to the catalog."""
    import asyncio

    return await asyncio.to_thread(model_service.search_catalog, q, 20)


@system_router.post(
    "/system/catalog/add",
    dependencies=[Depends(verify_api_key)],
)
async def add_catalog_model(
    payload: dict[str, str],
    model_service: ModelService = Depends(get_model_service),
) -> dict[str, Any]:
    """Add a Hugging Face GGUF repo to the catalog (all its variants become available)."""
    import asyncio

    repo_id = payload.get("repo_id", "").strip()
    if not repo_id:
        return {"error": "repo_id required"}
    return await asyncio.to_thread(model_service.add_hf_model, repo_id)


@system_router.post(
    "/system/benchmark",
    dependencies=[Depends(verify_api_key)],
)
async def trigger_benchmark(
    payload: dict[str, Any],
    model_service: ModelService = Depends(get_model_service),
) -> dict[str, Any]:
    """Trigger a standardized benchmark run on a model."""
    model_id = payload.get("model", "")
    iterations = payload.get("iterations", 3)

    settings = get_settings()
    benchmark_service = BenchmarkService(settings, model_service)
    return await benchmark_service.run_benchmark(model_id, iterations)


@system_router.get(
    "/system/benchmark/history",
    dependencies=[Depends(verify_api_key)],
)
async def get_benchmark_history(
    model_service: ModelService = Depends(get_model_service),
) -> list[dict[str, Any]]:
    """Retrieve historical benchmark runs."""
    settings = get_settings()
    benchmark_service = BenchmarkService(settings, model_service)
    return benchmark_service.get_history()
