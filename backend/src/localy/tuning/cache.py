"""
Tuning cache — persist tuning results and benchmark data across sessions.

Cache is keyed by hardware_hash + model_hash so optimal settings are reused
without re-benchmarking on every launch. Cache invalidates automatically
when hardware changes or llama-cpp-python is upgraded.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from localy.core.logging import get_logger
from localy.tuning.optimizer import InferenceConfig

logger = get_logger(__name__)

CACHE_FILENAME = "tuning_cache.json"


class TuningCache:
    """Persistent cache for auto-tuning results.

    Keyed by hardware_hash + model identifier, so settings are reused
    across sessions without re-computation.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_file = cache_dir / CACHE_FILENAME
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self._cache_file.exists():
            try:
                self._data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                logger.debug("tuning_cache_loaded", entries=len(self._data))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("tuning_cache_load_failed", error=str(e))
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(
                json.dumps(self._data, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("tuning_cache_save_failed", error=str(e))

    def _make_key(self, hardware_hash: str, model_id: str) -> str:
        """Create cache key from hardware hash and model identifier."""
        return f"{hardware_hash}:{model_id}"

    def get(self, hardware_hash: str, model_id: str) -> InferenceConfig | None:
        """Retrieve cached tuning config.

        Args:
            hardware_hash: Hardware profile hash.
            model_id: Model identifier (name or file hash).

        Returns:
            Cached InferenceConfig or None if not found.
        """
        key = self._make_key(hardware_hash, model_id)
        entry = self._data.get(key)
        if entry is None:
            return None

        try:
            return InferenceConfig(**entry["config"])
        except (KeyError, TypeError) as e:
            logger.debug("tuning_cache_entry_invalid", key=key, error=str(e))
            return None

    def put(self, hardware_hash: str, model_id: str, config: InferenceConfig) -> None:
        """Store tuning config in cache.

        Args:
            hardware_hash: Hardware profile hash.
            model_id: Model identifier.
            config: Computed inference configuration.
        """
        key = self._make_key(hardware_hash, model_id)
        self._data[key] = {
            "config": asdict(config),
            "hardware_hash": hardware_hash,
            "model_id": model_id,
        }
        self._save()
        logger.debug("tuning_cache_updated", key=key)

    def invalidate(self, hardware_hash: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            hardware_hash: If provided, only invalidate entries for this hardware.
                          If None, clear all entries.
        """
        if hardware_hash is None:
            self._data.clear()
            logger.info("tuning_cache_cleared")
        else:
            keys_to_remove = [
                k for k, v in self._data.items()
                if v.get("hardware_hash") == hardware_hash
            ]
            for k in keys_to_remove:
                del self._data[k]
            logger.info("tuning_cache_invalidated", hardware_hash=hardware_hash, removed=len(keys_to_remove))

        self._save()
