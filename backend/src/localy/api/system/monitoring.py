"""
System monitoring and diagnostics API router.

Exposes endpoints for health checking, hardware probing, and benchmark runs.
"""

from __future__ import annotations

import io
from typing import Any
from fastapi import APIRouter, Depends, File, UploadFile, status

from localy.core.config import get_settings
from localy.core.dependencies import (
    get_hardware_report,
    get_model_service,
    require_local,
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


# Cap extracted text so a huge document can't blow past the model's context.
_MAX_EXTRACT_CHARS = 30000


@system_router.post("/system/extract", dependencies=[Depends(verify_api_key)])
async def extract_document(file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract plain text from an uploaded document so it can be used as chat
    context. Handles PDFs (via pypdf) and any UTF-8/Latin-1 text or code file.
    Text is truncated to a safe length; the caller is told if it was cut."""
    raw = await file.read()
    name = (file.filename or "file").strip()
    lower = name.lower()

    text = ""
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            pages = [(p.extract_text() or "") for p in reader.pages]
            text = "\n\n".join(pages).strip()
        except Exception as e:  # noqa: BLE001 - report, don't crash
            return {"filename": name, "text": "", "chars": 0, "truncated": False, "error": f"Could not read PDF: {e}"}
    else:
        # Text / code / markdown / json / csv, etc. Decode leniently.
        for enc in ("utf-8", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue

    truncated = len(text) > _MAX_EXTRACT_CHARS
    if truncated:
        text = text[:_MAX_EXTRACT_CHARS]
    return {"filename": name, "text": text, "chars": len(text), "truncated": truncated}


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


# ===========================
# Background downloads (run server-side; survive UI navigation)
# ===========================


@system_router.post("/system/downloads/start", dependencies=[Depends(require_local)])
async def download_start(payload: dict[str, str]) -> dict[str, Any]:
    """Start (or resume) a background download. Returns immediately."""
    from localy.services.download_manager import get_download_manager

    model = payload.get("model", "").strip()
    if not model:
        return {"error": "model required"}
    return get_download_manager(get_settings()).start(model)


@system_router.get("/system/downloads", dependencies=[Depends(verify_api_key)])
async def download_status() -> list[dict[str, Any]]:
    """Progress of all downloads this session (poll this from the UI)."""
    from localy.services.download_manager import get_download_manager

    return get_download_manager(get_settings()).status()


@system_router.post("/system/downloads/cancel", dependencies=[Depends(require_local)])
async def download_cancel(payload: dict[str, str]) -> dict[str, Any]:
    """Cancel a background download (the partial file is kept for resume)."""
    from localy.services.download_manager import get_download_manager

    return get_download_manager(get_settings()).cancel(payload.get("model", ""))


# ===========================
# API access: keys + tunnel (management is loopback-only)
# ===========================


@system_router.get("/system/access", dependencies=[Depends(require_local)])
async def get_access() -> dict[str, Any]:
    """Everything the app needs to show the API Access panel."""
    from localy.core.api_keys import get_key_store
    from localy.network.tunnel import get_tunnel_manager
    from localy.pooling.discovery import _local_ip

    settings = get_settings()
    ip = _local_ip()
    port = settings.port
    return {
        "lan_url": f"http://{ip}:{port}/v1",
        "local_url": f"http://127.0.0.1:{port}/v1",
        "port": port,
        "keys": get_key_store(settings.config_path).list_masked(),
        "tunnel": get_tunnel_manager(settings).status(),
    }


@system_router.post("/system/keys", dependencies=[Depends(require_local)])
async def create_key(payload: dict[str, str]) -> dict[str, Any]:
    """Generate a new API key. The full key is returned ONCE — copy it now."""
    from localy.core.api_keys import get_key_store

    settings = get_settings()
    return get_key_store(settings.config_path).generate(payload.get("label", ""))


@system_router.delete("/system/keys/{key_id}", dependencies=[Depends(require_local)])
async def revoke_key(key_id: str) -> dict[str, bool]:
    """Revoke an API key."""
    from localy.core.api_keys import get_key_store

    settings = get_settings()
    return {"revoked": get_key_store(settings.config_path).revoke(key_id)}


@system_router.post("/system/tunnel/start", dependencies=[Depends(require_local)])
async def tunnel_start() -> dict[str, Any]:
    """Expose the API to the internet via a Cloudflare quick tunnel."""
    import asyncio

    from localy.network.tunnel import get_tunnel_manager

    settings = get_settings()
    mgr = get_tunnel_manager(settings)
    return await asyncio.to_thread(mgr.start, settings.port)


@system_router.post("/system/tunnel/stop", dependencies=[Depends(require_local)])
async def tunnel_stop() -> dict[str, Any]:
    """Stop the internet tunnel."""
    from localy.network.tunnel import get_tunnel_manager

    return get_tunnel_manager(get_settings()).stop()
