"""
Fast, resumable, atomic file downloads.

- Parallel: splits the file into ranges downloaded over several connections.
- Atomic: writes to `<dest>.part` and renames to `<dest>` only when complete, so
  an interrupted download never looks like a finished model.
- Resumable: a small `.part.state` file records completed chunks, so a retry
  (even after app restart) skips what's already done.
- Cancellable + progress callbacks.

Falls back to a single stream when the server doesn't support range requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Callable

import httpx

from localy.core.exceptions import DownloadCancelledError, DownloadError
from localy.core.logging import get_logger

logger = get_logger(__name__)

ProgressCallback = Callable[[int, int, float], None]

_CHUNK_SIZE = 32 * 1024 * 1024  # 32 MB per resumable chunk
_DEFAULT_CONNECTIONS = 4  # fewer parallel connections = fewer CDN resets


async def _probe(url: str, timeout: int) -> tuple[int, bool]:
    """Return (total_bytes, supports_range)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, read=60), follow_redirects=True) as c:
        # A ranged GET for 1 byte is the most reliable probe across CDNs.
        r = await c.get(url, headers={"Range": "bytes=0-0"})
        if r.status_code == 206:
            cr = r.headers.get("Content-Range", "")
            total = int(cr.split("/")[-1]) if "/" in cr else 0
            return total, total > 0
        # No range support; use Content-Length from a normal request.
        total = int(r.headers.get("Content-Length", "0") or 0)
        return total, False


async def _download_chunk(
    client: httpx.AsyncClient,
    url: str,
    part: Path,
    index: int,
    start: int,
    end: int,
    on_bytes: Callable[[int], None],
    cancel_check: Callable[[], bool] | None,
    max_retries: int = 5,
) -> None:
    """Download byte range [start, end] into `part`, retrying transient errors.

    Parallel connections to a CDN frequently get reset — retry each chunk with
    backoff so one dropped connection doesn't fail the whole download.
    """
    headers = {"Range": f"bytes={start}-{end}"}
    for attempt in range(max_retries):
        written = 0
        try:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    raise DownloadError(f"HTTP {resp.status_code} for chunk {index}")
                with part.open("r+b") as f:
                    f.seek(start)
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        if cancel_check and cancel_check():
                            raise DownloadCancelledError("cancelled")
                        f.write(chunk)
                        written += len(chunk)
                        on_bytes(len(chunk))
            return
        except DownloadCancelledError:
            raise
        except Exception as e:  # network reset, timeout, etc.
            on_bytes(-written)  # roll back this attempt's progress before retrying
            if attempt == max_retries - 1:
                raise DownloadError(f"chunk {index} failed after {max_retries} tries: {e!r}") from e
            await asyncio.sleep(1.5 * (attempt + 1))


async def download_file(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    progress_callback: ProgressCallback | None = None,
    connections: int = _DEFAULT_CONNECTIONS,
    timeout_seconds: int = 30,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """Download `url` to `destination` in parallel, atomically, resumably."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    state_path = destination.with_name(destination.name + ".part.state")

    if destination.exists():
        return destination  # already complete

    total, supports_range = await _probe(url, timeout_seconds)

    # ---- single-stream fallback (no range support / unknown size) ----
    if not supports_range or total <= 0 or connections <= 1:
        await _single_stream(url, part, total, progress_callback, timeout_seconds, cancel_check)
        _finalize(part, destination, state_path, expected_sha256)
        return destination

    # ---- parallel chunked download ----
    n_chunks = (total + _CHUNK_SIZE - 1) // _CHUNK_SIZE
    done: set[int] = set()
    if state_path.exists() and part.exists():
        try:
            st = json.loads(state_path.read_text())
            if st.get("total") == total and st.get("chunk_size") == _CHUNK_SIZE:
                done = set(st.get("done", []))
        except Exception:
            done = set()

    # Preallocate the part file to full size (once).
    if not part.exists() or part.stat().st_size != total:
        with part.open("wb") as f:
            f.truncate(total)
        done = set()

    start_time = time.monotonic()
    downloaded = [len(done) * _CHUNK_SIZE]  # mutable counter shared across chunk tasks
    last_emit = [start_time]
    lock = asyncio.Lock()

    def _save_state() -> None:
        state_path.write_text(json.dumps({"total": total, "chunk_size": _CHUNK_SIZE, "done": sorted(done)}))

    def _bump(n: int) -> None:
        downloaded[0] += n
        now = time.monotonic()
        if progress_callback and (now - last_emit[0]) >= 0.15:
            speed = (downloaded[0] / (1024 * 1024)) / (now - start_time) if now > start_time else 0
            progress_callback(min(downloaded[0], total), total, speed)
            last_emit[0] = now

    sem = asyncio.Semaphore(connections)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, read=120), follow_redirects=True) as client:
        async def worker(i: int) -> None:
            if i in done:
                return
            start = i * _CHUNK_SIZE
            end = min(start + _CHUNK_SIZE, total) - 1
            async with sem:
                await _download_chunk(client, url, part, i, start, end, _bump, cancel_check)
            async with lock:
                done.add(i)
                _save_state()

        try:
            await asyncio.gather(*(worker(i) for i in range(n_chunks)))
        except DownloadCancelledError:
            _save_state()
            raise

    if progress_callback:
        progress_callback(total, total, 0.0)
    _finalize(part, destination, state_path, expected_sha256)
    return destination


async def _single_stream(
    url: Path | str,
    part: Path,
    total: int,
    progress_callback: ProgressCallback | None,
    timeout_seconds: int,
    cancel_check: Callable[[], bool] | None,
) -> None:
    resume_from = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    start_time = time.monotonic()
    downloaded = resume_from
    last_emit = start_time
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, read=300), follow_redirects=True) as client:
        async with client.stream("GET", str(url), headers=headers) as resp:
            if resp.status_code == 416:
                return
            if resp.status_code not in (200, 206):
                raise DownloadError(f"HTTP {resp.status_code}")
            mode = "ab" if resp.status_code == 206 else "wb"
            if mode == "wb":
                downloaded = 0
            with part.open(mode) as f:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                    if cancel_check and cancel_check():
                        raise DownloadCancelledError("cancelled")
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if progress_callback and (now - last_emit) >= 0.15:
                        speed = (downloaded / (1024 * 1024)) / (now - start_time) if now > start_time else 0
                        progress_callback(downloaded, total or downloaded, speed)
                        last_emit = now


def _finalize(part: Path, destination: Path, state_path: Path, expected_sha256: str | None) -> None:
    """Verify (if hash given) and atomically rename .part -> destination."""
    if expected_sha256:
        h = hashlib.sha256()
        with part.open("rb") as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
        if h.hexdigest() != expected_sha256:
            part.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            raise DownloadError("SHA256 mismatch — download corrupted", error_code="LOCALY_DOWNLOAD_HASH_MISMATCH")
    part.replace(destination)  # atomic on same filesystem
    state_path.unlink(missing_ok=True)
