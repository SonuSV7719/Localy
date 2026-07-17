"""
Localy Hardware Service.

Provides interface for querying hardware capability reports and assessing
model compatibility.
"""

from __future__ import annotations

from typing import Any

from localy.core.config import Settings
from localy.core.logging import get_logger
from localy.hardware.report import run_full_probe
from localy.tuning.advisor import assess_model_fit
from localy.inference.model_registry import ModelRegistry

logger = get_logger(__name__)


class HardwareService:
    """Manages hardware probing and model fit recommendations."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._registry = ModelRegistry(settings.config_path)

    def get_hardware_report(self) -> dict[str, Any]:
        """Run hardware probe and return full serialization."""
        report = run_full_probe(self._settings.models_path)
        return report.to_dict()

    def get_fit_assessment(self, model_spec: str, target_context: int | None = None) -> dict[str, Any]:
        """Assess compatibility for a specific model on this machine."""
        entry, variant = self._registry.resolve(model_spec)
        report = run_full_probe(self._settings.models_path)
        context = target_context or self._settings.default_context_length

        fit = assess_model_fit(
            report=report,
            model_name=entry.display_name,
            parameter_count_billions=entry.parameter_count_billions,
            quantization=variant.quantization,
            target_context=context,
            actual_size_bytes=getattr(variant, "file_size_bytes", None),
        )

        return {
            "model_id": entry.full_id,
            "fit_level": fit.fit_level.value,
            "explanation": fit.explanation,
            "recommendations": fit.recommendations,
            "max_context": fit.max_context,
            "memory_budget_bytes": fit.memory_budget_bytes,
            "memory_usage_bytes": fit.memory_usage_bytes,
            "headroom_bytes": fit.headroom_bytes,
        }
