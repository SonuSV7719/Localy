"""
Localy GGUF model store manager.

Handles physical storage operations: listing local files, deleting files, checking disk space,
and validating file integrity.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from localy.core.exceptions import InsufficientStorageError, ModelNotFoundError
from localy.core.logging import get_logger
from localy.utils.hashing import verify_file_integrity

if TYPE_CHECKING:
    from localy.core.config import Settings

logger = get_logger(__name__)


class LocalModelInfo(TypedDict):
    """Information about a locally stored model file."""
    filename: str
    path: str
    size_bytes: int
    modified_at: float


class ModelStore:
    """Manages model files stored locally in the models directory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._models_path = settings.models_path
        self._models_path.mkdir(parents=True, exist_ok=True)

    def list_local_models(self) -> list[LocalModelInfo]:
        """List all GGUF model files currently stored locally."""
        local_models: list[LocalModelInfo] = []
        if not self._models_path.exists():
            return local_models

        for path in self._models_path.glob("*.gguf"):
            try:
                stat = path.stat()
                local_models.append(
                    {
                        "filename": path.name,
                        "path": str(path),
                        "size_bytes": stat.st_size,
                        "modified_at": stat.st_mtime,
                    }
                )
            except OSError as e:
                logger.error("failed_to_stat_model_file", path=str(path), error=str(e))

        return sorted(local_models, key=lambda x: x["filename"])

    def delete_model(self, filename: str) -> None:
        """Delete a local model file.

        Args:
            filename: Name of the GGUF file.

        Raises:
            ModelNotFoundError: If the file does not exist.
        """
        path = self._models_path / filename
        if not path.exists():
            raise ModelNotFoundError(
                f"Model file '{filename}' not found in storage.",
                details={"filename": filename, "directory": str(self._models_path)},
            )

        import gc
        import time

        last_err: Exception | None = None
        for attempt in range(4):
            try:
                path.unlink()
                logger.info("model_deleted", filename=filename, path=str(path))
                return
            except PermissionError as e:  # Windows: file lock may linger after unload
                last_err = e
                gc.collect()
                time.sleep(0.5)
            except OSError as e:
                logger.error("failed_to_delete_model", filename=filename, error=str(e))
                raise
        logger.error("failed_to_delete_model", filename=filename, error=str(last_err))
        raise last_err  # type: ignore[misc]

    def has_model(self, filename: str, expected_size: int | None = None) -> bool:
        """Check if a model file exists locally and optionally has the expected size.

        Args:
            filename: GGUF filename.
            expected_size: Optional expected size in bytes.

        Returns:
            True if exists (and size matches), False otherwise.
        """
        path = self._models_path / filename
        if not path.exists():
            return False

        if expected_size is not None:
            try:
                return path.stat().st_size == expected_size
            except OSError:
                return False

        return True

    def verify_integrity(self, filename: str, expected_sha256: str) -> bool:
        """Verify the integrity of a downloaded model file via SHA256.

        Args:
            filename: GGUF filename.
            expected_sha256: Expected SHA256 hash.

        Returns:
            True if matching, False if mismatched or file not found.
        """
        path = self._models_path / filename
        return verify_file_integrity(path, expected_sha256)

    def get_disk_space(self) -> dict[str, int]:
        """Get disk space information for the partition containing the model store.

        Returns:
            Dict containing total, used, and free space in bytes.
        """
        total, used, free = shutil.disk_usage(self._models_path)
        return {
            "total": total,
            "used": used,
            "free": free,
        }

    def verify_disk_budget(self, required_bytes: int, safety_buffer_bytes: int = 500 * 1024 * 1024) -> None:
        """Verify that there is enough disk space for a download, plus a safety buffer.

        Args:
            required_bytes: Number of bytes needed for download.
            safety_buffer_bytes: Safety buffer to avoid filling the disk entirely.

        Raises:
            InsufficientStorageError: If free disk space is less than required + buffer.
        """
        space = self.get_disk_space()
        free = space["free"]
        needed = required_bytes + safety_buffer_bytes

        if free < needed:
            raise InsufficientStorageError(
                f"Insufficient disk space. Needed: {needed / (1024**3):.2f} GB, "
                f"Free: {free / (1024**3):.2f} GB.",
                details={
                    "free_bytes": free,
                    "required_bytes": required_bytes,
                    "needed_bytes_with_buffer": needed,
                },
            )
