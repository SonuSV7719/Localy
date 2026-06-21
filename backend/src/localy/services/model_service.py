"""
Localy Model Service.

Provides a high-level service layer for listing, fetching, downloading, verifying,
and loading GGUF models with optimal configurations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from localy.core.config import Settings
from localy.core.exceptions import ModelNotFoundError
from localy.core.logging import get_logger
from localy.hardware.report import run_full_probe
from localy.inference.engine import get_engine
from localy.inference.model_manager import ModelManager
from localy.tuning.advisor import assess_model_fit
from localy.tuning.optimizer import compute_inference_config

if TYPE_CHECKING:
    from localy.storage.model_store import ModelStore
    from localy.inference.types import LoadedModelInfo

logger = get_logger(__name__)


class ModelService:
    """Manages the lifecycle and scheduling of models."""

    def __init__(self, settings: Settings, store: ModelStore) -> None:
        self._settings = settings
        self._store = store
        self._manager = ModelManager(settings, store)

    def list_models(self) -> list[dict[str, Any]]:
        """List all models in the registry annotated with local status and hardware fit."""
        registry_models = self._manager.registry.list_models()
        local_files = {f["filename"]: f for f in self._store.list_local_models()}
        probe_report = run_full_probe(self._settings.models_path)

        models_list: list[dict[str, Any]] = []

        for entry in registry_models:
            variants_info = []
            for quant, var in entry.variants.items():
                is_downloaded = var.huggingface_file in local_files
                local_file_info = local_files.get(var.huggingface_file)

                # Assess hardware fit
                fit = assess_model_fit(
                    report=probe_report,
                    model_name=entry.display_name,
                    parameter_count_billions=entry.parameter_count_billions,
                    quantization=quant,
                    target_context=self._settings.default_context_length,
                )

                variants_info.append(
                    {
                        "quantization": quant,
                        "file_size_bytes": var.file_size_bytes,
                        "is_downloaded": is_downloaded,
                        "local_path": local_file_info["path"] if is_downloaded else None,
                        "fit_level": fit.fit_level.value,
                        "fit_explanation": fit.explanation,
                        "recommendations": fit.recommendations,
                        "max_context": fit.max_context,
                    }
                )

            models_list.append(
                {
                    "id": entry.full_id,
                    "name": entry.name,
                    "display_name": entry.display_name,
                    "family": entry.family,
                    "parameter_count_billions": entry.parameter_count_billions,
                    "description": entry.description,
                    "license": entry.license,
                    "context_length": entry.context_length,
                    "tags": entry.tags,
                    "variants": variants_info,
                }
            )

        return models_list

    async def get_active_model(self) -> LoadedModelInfo | None:
        """Get the active model info from the engine."""
        engine = get_engine(self._settings)
        return await engine.get_loaded_model_info()

    async def load_model(self, model_spec: str, context_length: int | None = None) -> LoadedModelInfo:
        """Load a model using the optimal config for this machine."""
        entry, variant = self._manager.registry.resolve(model_spec)
        model_path = self._manager.get_local_model_path(model_spec)

        logger.info("requesting_model_load", model_spec=model_spec)

        # Run probe and compute optimal config
        report = run_full_probe(self._settings.models_path)
        config = compute_inference_config(
            report=report,
            model_size_bytes=model_path.stat().st_size,
            requested_context=context_length,
            profile=self._settings.tuning_profile,
            thread_override=self._settings.thread_count_override,
            batch_override=self._settings.batch_size_override,
        )

        engine = get_engine(self._settings)
        await engine.load_model(
            model_id=entry.full_id,
            model_path=model_path,
            config=config,
        )

        info = await engine.get_loaded_model_info()
        if info is None:
            raise RuntimeError("Model reported loaded but engine returned no loaded model info.")
        return info

    async def unload_model(self) -> None:
        """Unload any loaded model."""
        engine = get_engine(self._settings)
        await engine.unload_model()

    async def pull_model(
        self,
        model_spec: str,
        progress_callback: Callable[[int, int, float], None] | None = None,
        force: bool = False,
    ) -> Path:
        """Download model weights."""
        return await self._manager.pull_model(model_spec, progress_callback, force)

    def delete_model(self, model_spec: str) -> None:
        """Delete model weights from disk."""
        self._manager.delete_model(model_spec)
