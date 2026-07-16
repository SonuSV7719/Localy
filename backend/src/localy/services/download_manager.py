"""
Background download manager.

Downloads run as server-side asyncio tasks, decoupled from any HTTP request or
UI page — so switching tabs, closing the catalog, or a dropped connection never
stops a download. The UI just polls `status()` for progress. Downloads are
parallel, atomic, and resumable (see utils.download).
"""

from __future__ import annotations

import asyncio
from typing import Any

from localy.core.config import Settings
from localy.core.exceptions import DownloadCancelledError
from localy.core.logging import get_logger
from localy.inference.model_manager import ModelManager
from localy.storage.model_store import ModelStore
from localy.utils.download import download_file

logger = get_logger(__name__)


class DownloadManager:
    """Tracks and runs model downloads in the background."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._manager = ModelManager(settings, ModelStore(settings))
        self._state: dict[str, dict[str, Any]] = {}  # model_id -> progress state
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel: dict[str, bool] = {}

    def start(self, model_id: str) -> dict[str, Any]:
        """Begin (or resume) a background download. Returns immediately."""
        existing = self._state.get(model_id)
        if existing and existing.get("status") == "downloading":
            return existing

        model, variant = self._manager.registry.resolve(model_id)
        dest = self._settings.models_path / variant.huggingface_file
        if dest.exists():
            st = {"model_id": model_id, "status": "done", "completed": 0, "total": 0, "speed_mbps": 0}
            self._state[model_id] = st
            return st

        self._settings.models_path.mkdir(parents=True, exist_ok=True)
        self._cancel[model_id] = False
        st = {
            "model_id": model_id,
            "label": model.display_name,
            "status": "downloading",
            "completed": 0,
            "total": variant.file_size_bytes,
            "speed_mbps": 0.0,
            "error": None,
        }
        self._state[model_id] = st
        self._tasks[model_id] = asyncio.create_task(
            self._run(model_id, variant.resolved_download_url, dest, variant.sha256 or None)
        )
        logger.info("download_started_bg", model=model_id)
        return st

    async def _run(self, model_id: str, url: str, dest, sha256: str | None) -> None:
        def cb(done: int, total: int, speed: float) -> None:
            s = self._state.get(model_id)
            if s:
                s["completed"] = done
                if total:
                    s["total"] = total
                s["speed_mbps"] = round(speed, 2)

        try:
            await download_file(
                url,
                dest,
                expected_sha256=sha256,
                progress_callback=cb,
                cancel_check=lambda: self._cancel.get(model_id, False),
            )
            self._state[model_id]["status"] = "done"
            self._state[model_id]["speed_mbps"] = 0.0
            logger.info("download_done_bg", model=model_id)
        except DownloadCancelledError:
            self._state[model_id]["status"] = "cancelled"
            logger.info("download_cancelled_bg", model=model_id)
        except Exception as e:  # noqa: BLE001
            self._state[model_id]["status"] = "error"
            self._state[model_id]["error"] = str(e)
            logger.error("download_error_bg", model=model_id, error=str(e))
        finally:
            self._tasks.pop(model_id, None)
            self._cancel.pop(model_id, None)

    def cancel(self, model_id: str) -> dict[str, Any]:
        """Request cancellation. The .part is kept so it can be resumed later."""
        if model_id in self._tasks:
            self._cancel[model_id] = True
        return {"model_id": model_id, "cancelling": model_id in self._tasks}

    def status(self) -> list[dict[str, Any]]:
        """Progress of all known downloads this session."""
        return list(self._state.values())

    def clear_finished(self) -> None:
        for mid in [m for m, s in self._state.items() if s.get("status") in ("done", "error", "cancelled")]:
            self._state.pop(mid, None)


_manager: DownloadManager | None = None


def get_download_manager(settings: Settings) -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager(settings)
    return _manager
