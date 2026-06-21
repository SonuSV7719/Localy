"""
Localy Model Manager.

Coordinates model catalog registry access, model downloads (with resume support and SHA256 checking),
and local storage mapping.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from localy.core.exceptions import DownloadError, ModelNotFoundError
from localy.core.logging import get_logger
from localy.inference.model_registry import ModelRegistry
from localy.utils.download import download_file

if TYPE_CHECKING:
    from localy.core.config import Settings
    from localy.storage.model_store import ModelStore, LocalModelInfo

logger = get_logger(__name__)


class ModelManager:
    """Orchestrates model registries, downloads, verification, and file storage."""

    def __init__(self, settings: Settings, store: ModelStore) -> None:
        self._settings = settings
        self._store = store
        self._registry = ModelRegistry(settings.config_path)

    @property
    def registry(self) -> ModelRegistry:
        """Get the model registry instance."""
        return self._registry

    def list_local_models(self) -> list[LocalModelInfo]:
        """List all model files stored locally."""
        return self._store.list_local_models()

    def get_local_model_path(self, model_spec: str) -> Path:
        """Get the local filesystem path for a model specification if downloaded.

        Args:
            model_spec: Ollama-style model specification.

        Returns:
            Path to local GGUF file.

        Raises:
            ModelNotFoundError: If the model is not in registry or not downloaded.
        """
        model, variant = self._registry.resolve(model_spec)
        filename = variant.huggingface_file
        if not self._store.has_model(filename):
            raise ModelNotFoundError(
                f"Model '{model_spec}' is not downloaded locally.",
                details={"model": model.display_name, "filename": filename},
            )
        return self._settings.models_path / filename

    async def pull_model(
        self,
        model_spec: str,
        progress_callback: Callable[[int, int, float], None] | None = None,
        force: bool = False,
    ) -> Path:
        """Download and verify a model by name.

        Args:
            model_spec: Ollama-style model specification.
            progress_callback: Optional progress callback.
            force: Re-download even if already present.

        Returns:
            Path to the verified local GGUF file.
        """
        model, variant = self._registry.resolve(model_spec)
        filename = variant.huggingface_file
        destination = self._settings.models_path / filename

        # Check if already downloaded and verified
        if destination.exists() and not force:
            logger.info("model_already_downloaded", filename=filename)
            # Integrity check
            if variant.sha256:
                is_valid = self._store.verify_integrity(filename, variant.sha256)
                if is_valid:
                    return destination
                else:
                    logger.warning("model_corrupted_redownloading", filename=filename)
            else:
                return destination

        # Check storage space
        self._store.verify_disk_budget(variant.file_size_bytes)

        url = variant.resolved_download_url
        logger.info("starting_model_download", model=model.display_name, url=url)

        try:
            await download_file(
                url=url,
                destination=destination,
                expected_sha256=variant.sha256 or None,
                progress_callback=progress_callback,
            )
        except Exception as e:
            logger.error("model_download_failed", model=model.display_name, error=str(e))
            raise DownloadError(f"Failed to download model '{model.display_name}': {e}") from e

        return destination

    def delete_model(self, model_spec: str) -> None:
        """Delete local model file.

        Args:
            model_spec: Ollama-style model specification.
        """
        _, variant = self._registry.resolve(model_spec)
        self._store.delete_model(variant.huggingface_file)
