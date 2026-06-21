"""
Resumable HTTP downloads with progress tracking and SHA256 verification.

Handles multi-GB model file downloads with:
- Resume support (Range headers) for interrupted downloads
- Real-time progress callbacks for UI integration
- Streaming SHA256 verification during download (no second pass)
- Retry with exponential backoff on transient failures
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from localy.core.exceptions import DownloadCancelledError, DownloadError
from localy.core.logging import get_logger

logger = get_logger(__name__)

# Type for progress callback: (downloaded_bytes, total_bytes, speed_mbps) -> None
ProgressCallback = Callable[[int, int, float], None]


async def download_file(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    progress_callback: ProgressCallback | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    timeout_seconds: int = 30,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """Download a file with resume support and progress tracking.

    Args:
        url: URL to download from.
        destination: Local file path to save to.
        expected_sha256: Expected SHA256 hash for verification. None to skip.
        progress_callback: Called with (downloaded, total, speed_mbps).
        headers: Additional HTTP headers.
        max_retries: Maximum retry attempts on transient failures.
        timeout_seconds: Connection timeout in seconds.
        cancel_check: Callable returning True if download should be cancelled.

    Returns:
        Path to the downloaded file.

    Raises:
        DownloadError: If download fails after all retries.
        DownloadCancelledError: If download is cancelled via cancel_check.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Check for partial download (resume support)
    downloaded_bytes = 0
    if destination.exists():
        downloaded_bytes = destination.stat().st_size

    request_headers = dict(headers or {})

    for attempt in range(max_retries):
        try:
            # Set Range header for resume
            if downloaded_bytes > 0:
                request_headers["Range"] = f"bytes={downloaded_bytes}-"
                logger.info("download_resuming", url=url, from_byte=downloaded_bytes)

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds, read=300),
                follow_redirects=True,
            ) as client:
                async with client.stream("GET", url, headers=request_headers) as response:
                    if response.status_code == 416:
                        # Range not satisfiable — file already complete
                        logger.info("download_already_complete", url=url)
                        break

                    if response.status_code not in {200, 206}:
                        raise DownloadError(  # noqa: TRY301
                            f"HTTP {response.status_code}: {response.reason_phrase}",
                            details={"url": url, "status": response.status_code},
                        )

                    # Get total size from Content-Range or Content-Length
                    total_bytes = _get_total_size(response, downloaded_bytes)

                    hasher = hashlib.sha256()
                    mode = "ab" if response.status_code == 206 else "wb"  # noqa: PLR2004
                    if mode == "wb":
                        downloaded_bytes = 0

                    # If we're resuming, we need to hash existing content first
                    if mode == "ab" and downloaded_bytes > 0 and expected_sha256:
                        hasher = _hash_existing(destination, hasher)

                    start_time = time.monotonic()
                    last_progress_time = start_time

                    with destination.open(mode) as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):  # 1MB chunks
                            # Check cancellation
                            if cancel_check and cancel_check():
                                raise DownloadCancelledError("Download cancelled by user")

                            f.write(chunk)
                            if expected_sha256:
                                hasher.update(chunk)
                            downloaded_bytes += len(chunk)

                            # Progress callback (throttled to max 10Hz)
                            now = time.monotonic()
                            if progress_callback and (now - last_progress_time) >= 0.1:
                                elapsed = now - start_time
                                speed_mbps = (downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                                progress_callback(downloaded_bytes, total_bytes, speed_mbps)
                                last_progress_time = now

                    # Final progress update
                    if progress_callback:
                        elapsed = time.monotonic() - start_time
                        speed_mbps = (downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        progress_callback(downloaded_bytes, total_bytes, speed_mbps)

            # Verify SHA256
            if expected_sha256:
                actual_hash = hasher.hexdigest()
                if actual_hash != expected_sha256:
                    # Delete corrupted file
                    destination.unlink(missing_ok=True)
                    raise DownloadError(  # noqa: TRY301
                        f"SHA256 mismatch: expected {expected_sha256[:16]}..., got {actual_hash[:16]}...",
                        error_code="LOCALY_DOWNLOAD_HASH_MISMATCH",
                        details={"expected": expected_sha256, "actual": actual_hash},
                    )

            logger.info(
                "download_complete",
                url=url,
                size_mb=round(downloaded_bytes / (1024 * 1024), 1),
                destination=str(destination),
            )
            return destination

        except DownloadCancelledError:
            raise

        except DownloadError:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning(
                "download_retry",
                attempt=attempt + 1,
                max_retries=max_retries,
                wait_seconds=wait,
            )
            time.sleep(wait)

        except Exception as e:
            if attempt == max_retries - 1:
                raise DownloadError(
                    f"Download failed after {max_retries} attempts: {e}",
                    details={"url": url, "error": str(e)},
                ) from e
            wait = 2 ** attempt
            logger.warning("download_retry", attempt=attempt + 1, wait_seconds=wait, error=str(e))
            time.sleep(wait)

    return destination


def _get_total_size(response: httpx.Response, already_downloaded: int) -> int:
    """Extract total file size from response headers."""
    content_range = response.headers.get("Content-Range")
    if content_range:
        # Format: "bytes start-end/total"
        try:
            total = int(content_range.split("/")[-1])
            return total
        except (ValueError, IndexError):
            pass

    content_length = response.headers.get("Content-Length")
    if content_length:
        return already_downloaded + int(content_length)

    return 0


def _hash_existing(path: Path, hasher: Any) -> Any:
    """Hash existing file content for resume verification."""
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher
