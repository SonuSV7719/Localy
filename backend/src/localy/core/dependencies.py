"""
Localy FastAPI dependency injection providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from fastapi import Depends, Security

from localy.core.config import Settings, get_settings
from localy.core.security import create_api_key_validator

if TYPE_CHECKING:
    from localy.hardware.report import HardwareReport
    from localy.inference.engine import InferenceEngine
    from localy.storage.model_store import ModelStore
    from localy.services.model_service import ModelService

# Cache singleton instances
_hardware_report: HardwareReport | None = None
_model_store: ModelStore | None = None
_model_service: ModelService | None = None


def get_api_key_validator(
    settings: Settings = Depends(get_settings),
):
    """Dependency to get API key validator."""
    return create_api_key_validator(settings)


async def verify_api_key(
    settings: Settings = Depends(get_settings),
    api_key_header: str | None = Security(create_api_key_validator(get_settings())),
) -> str | None:
    """Dependency to verify API key."""
    return api_key_header


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
