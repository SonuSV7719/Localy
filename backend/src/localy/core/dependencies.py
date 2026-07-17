"""
Localy FastAPI dependency injection providers.
"""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING
from fastapi import Depends, HTTPException, Request, status

from localy.core.api_keys import get_key_store
from localy.core.config import Settings, get_settings

if TYPE_CHECKING:
    from localy.hardware.report import HardwareReport
    from localy.inference.engine import InferenceEngine
    from localy.storage.model_store import ModelStore
    from localy.services.model_service import ModelService

# Cache singleton instances
_hardware_report: HardwareReport | None = None
_model_store: ModelStore | None = None
_model_service: ModelService | None = None


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _extract_key(request: Request) -> str | None:
    """Pull an API key from Authorization: Bearer … or X-API-Key."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key") or None


def _is_proxied(request: Request) -> bool:
    """True if the request came through a reverse proxy / tunnel.

    Cloudflare (and other tunnels) forward to 127.0.0.1 but add forwarding
    headers. Without this check, tunneled requests would look loopback and
    bypass the key — so any forwarded request must present a key.
    """
    h = request.headers
    return bool(
        h.get("x-forwarded-for")
        or h.get("cf-connecting-ip")
        or h.get("forwarded")
        or h.get("x-real-ip")
    )


async def verify_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Gate remote access. Genuine loopback (the app itself) is exempt; every
    LAN / internet / tunneled request must present a valid API key. Fail-closed:
    if no keys exist, non-loopback access is denied.
    """
    client = request.client.host if request.client else ""
    if client in _LOOPBACK_HOSTS and not _is_proxied(request):
        return None  # local app / CLI — always allowed

    key = _extract_key(request)
    store = get_key_store(settings.config_path)
    static_ok = bool(settings.api_key) and hmac.compare_digest(str(key or ""), str(settings.api_key))
    if store.is_valid(key) or static_ok:
        return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid API key is required for remote access. Generate one in the Localy app.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_local(request: Request) -> None:
    """Restrict an endpoint to loopback callers only (the app on this machine).

    Used for management endpoints (API keys, tunnels) so a remote key holder
    can never mint keys or change exposure — only the local owner can.
    """
    client = request.client.host if request.client else ""
    if client not in _LOOPBACK_HOSTS or _is_proxied(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is only allowed from the Localy app on the host machine.",
        )


def get_hardware_report(
    settings: Settings = Depends(get_settings),
) -> HardwareReport:
    """Get the cached hardware capability report.

    Runs full probe if not already cached.
    """
    global _hardware_report
    if _hardware_report is None:
        from localy.hardware.report import run_full_probe
        _hardware_report = run_full_probe(settings.models_path)
    return _hardware_report


def get_engine(
    settings: Settings = Depends(get_settings),
) -> InferenceEngine:
    """Get the singleton InferenceEngine instance."""
    from localy.inference.engine import get_engine as get_inference_engine
    return get_inference_engine(settings)


def get_model_store(
    settings: Settings = Depends(get_settings),
) -> ModelStore:
    """Get the ModelStore instance."""
    global _model_store
    if _model_store is None:
        from localy.storage.model_store import ModelStore
        _model_store = ModelStore(settings)
    return _model_store


def get_model_service(
    settings: Settings = Depends(get_settings),
    store: ModelStore = Depends(get_model_store),
) -> ModelService:
    """Get the ModelService instance."""
    global _model_service
    if _model_service is None:
        from localy.services.model_service import ModelService
        _model_service = ModelService(settings, store)
    return _model_service
