"""
Storage detection — disk space, read speed estimation, mmap suitability.

Disk I/O matters for model loading (GGUF files are multi-GB) and for
memory-mapped (mmap) loading which relies on the OS paging from disk.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from localy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class StorageInfo:
    """Storage information for the model directory drive.

    Attributes:
        path: The path being analyzed.
        total_bytes: Total drive capacity.
        free_bytes: Free space on the drive.
        used_bytes: Used space on the drive.
        percent_used: Usage percentage (0-100).
        read_speed_mbps: Estimated sequential read speed in MB/s (0 if unknown).
        is_ssd: Whether the drive appears to be an SSD (heuristic).
        mmap_recommended: Whether memory-mapped model loading is recommended.
    """

    path: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    percent_used: float
    read_speed_mbps: float = 0.0
    is_ssd: bool = True  # Assume SSD unless proven otherwise
    mmap_recommended: bool = True

    @property
    def free_gb(self) -> float:
        """Free space in GB."""
        return self.free_bytes / (1024**3)

    @property
    def total_gb(self) -> float:
        """Total capacity in GB."""
        return self.total_bytes / (1024**3)

    def can_fit_model(self, model_size_bytes: int) -> bool:
        """Check if there's enough free space for a model file.

        Args:
            model_size_bytes: Size of the model file to download.

        Returns:
            True if the model fits with some headroom.
        """
        # Require at least 1GB headroom beyond the model size
        headroom = 1024**3  # 1 GB
        return self.free_bytes >= (model_size_bytes + headroom)


def detect_storage(model_dir: Path) -> StorageInfo:
    """Detect storage information for the model directory drive.

    Args:
        model_dir: Path where models are/will be stored.

    Returns:
        StorageInfo for the drive containing model_dir.
    """
    logger.info("storage_detection_started", model_dir=str(model_dir))

    # Ensure the directory exists for disk_usage to work
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        usage = psutil.disk_usage(str(model_dir))
    except OSError:
        # If the specific path fails, try the drive root
        drive = Path(model_dir.anchor)
        usage = psutil.disk_usage(str(drive))

    # Estimate read speed with a small sequential read test
    read_speed = _estimate_read_speed(model_dir)

    # Heuristic SSD detection (if read speed > 200 MB/s, likely SSD)
    is_ssd = read_speed > 200.0 if read_speed > 0 else True  # noqa: PLR2004

    # mmap is recommended on SSDs with adequate free space
    mmap_recommended = is_ssd and (usage.free > 4 * 1024**3)  # At least 4GB free

    info = StorageInfo(
        path=str(model_dir),
        total_bytes=usage.total,
        free_bytes=usage.free,
        used_bytes=usage.used,
        percent_used=usage.percent,
        read_speed_mbps=read_speed,
        is_ssd=is_ssd,
        mmap_recommended=mmap_recommended,
    )

    logger.info(
        "storage_detected",
        free_gb=round(info.free_gb, 1),
        total_gb=round(info.total_gb, 1),
        read_speed_mbps=round(info.read_speed_mbps, 0),
        is_ssd=info.is_ssd,
        mmap_recommended=info.mmap_recommended,
    )

    return info


def _estimate_read_speed(directory: Path) -> float:
    """Estimate sequential read speed by reading a temporary file.

    Creates a small temp file, reads it, and measures throughput.
    Returns 0.0 if estimation fails.

    Args:
        directory: Directory to test read speed in.

    Returns:
        Estimated read speed in MB/s.
    """
    test_file = directory / ".localy_speed_test"
    test_size = 4 * 1024 * 1024  # 4 MB test file

    try:
        # Write test data
        test_data = b"\x00" * test_size
        test_file.write_bytes(test_data)

        # Read and time it (multiple iterations for accuracy)
        iterations = 3
        total_time = 0.0

        for _ in range(iterations):
            start = time.perf_counter()
            _ = test_file.read_bytes()
            total_time += time.perf_counter() - start

        avg_time = total_time / iterations
        speed_mbps = (test_size / (1024 * 1024)) / avg_time if avg_time > 0 else 0.0

        return speed_mbps

    except Exception as e:
        logger.debug("read_speed_estimation_failed", error=str(e))
        return 0.0

    finally:
        # Clean up
        try:
            test_file.unlink(missing_ok=True)
        except Exception:
            pass
