"""
Memory analysis — RAM detection, available memory, swap, and safe model budget.

The memory budget calculation is critical for the hardware-fit advisor:
- Total RAM − OS overhead − app overhead − safety margin = what's available for models
- If model + KV cache > budget → model doesn't fit → recommend smaller quant or pooling
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psutil

from localy.core.constants import (
    APP_MEMORY_OVERHEAD_BYTES,
    MEMORY_SAFETY_MARGIN,
    OS_MEMORY_OVERHEAD_LINUX_BYTES,
    OS_MEMORY_OVERHEAD_MACOS_BYTES,
    OS_MEMORY_OVERHEAD_WINDOWS_BYTES,
)
from localy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class MemoryInfo:
    """System memory information.

    Attributes:
        total_bytes: Total physical RAM in bytes.
        available_bytes: Currently available RAM in bytes.
        used_bytes: Currently used RAM in bytes.
        percent_used: Memory usage percentage (0-100).
        swap_total_bytes: Total swap space in bytes.
        swap_used_bytes: Currently used swap in bytes.
        os_overhead_bytes: Estimated OS memory overhead.
        safe_model_budget_bytes: Maximum bytes available for model loading.
    """

    total_bytes: int
    available_bytes: int
    used_bytes: int
    percent_used: float
    swap_total_bytes: int
    swap_used_bytes: int
    os_overhead_bytes: int
    safe_model_budget_bytes: int

    @property
    def total_gb(self) -> float:
        """Total RAM in GB (human-readable)."""
        return self.total_bytes / (1024**3)

    @property
    def available_gb(self) -> float:
        """Available RAM in GB (human-readable)."""
        return self.available_bytes / (1024**3)

    @property
    def safe_model_budget_gb(self) -> float:
        """Safe model budget in GB (human-readable)."""
        return self.safe_model_budget_bytes / (1024**3)

    @property
    def has_swap_pressure(self) -> bool:
        """Whether significant swap is being used (indicates memory pressure)."""
        if self.swap_total_bytes == 0:
            return False
        swap_percent = (self.swap_used_bytes / self.swap_total_bytes) * 100
        return swap_percent > 20  # noqa: PLR2004


def detect_memory() -> MemoryInfo:
    """Detect system memory information and calculate safe model budget.

    Returns:
        MemoryInfo with all memory metrics and computed budget.
    """
    logger.info("memory_detection_started")

    vmem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Determine OS overhead based on platform
    os_overhead = _get_os_overhead()

    # Calculate safe model budget:
    # total_ram - os_overhead - app_overhead, then apply safety margin
    raw_budget = vmem.total - os_overhead - APP_MEMORY_OVERHEAD_BYTES
    safe_budget = max(0, int(raw_budget * MEMORY_SAFETY_MARGIN))

    info = MemoryInfo(
        total_bytes=vmem.total,
        available_bytes=vmem.available,
        used_bytes=vmem.used,
        percent_used=vmem.percent,
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
        os_overhead_bytes=int(os_overhead),
        safe_model_budget_bytes=safe_budget,
    )

    logger.info(
        "memory_detected",
        total_gb=round(info.total_gb, 1),
        available_gb=round(info.available_gb, 1),
        safe_budget_gb=round(info.safe_model_budget_gb, 1),
        swap_pressure=info.has_swap_pressure,
    )

    if info.has_swap_pressure:
        logger.warning(
            "swap_pressure_detected",
            swap_used_mb=info.swap_used_bytes // (1024**2),
            msg="High swap usage detected. System may be under memory pressure.",
        )

    return info


def _get_os_overhead() -> float:
    """Get estimated OS memory overhead for the current platform."""
    if os.name == "nt":
        return OS_MEMORY_OVERHEAD_WINDOWS_BYTES
    try:
        import platform as plat

        if plat.system() == "Darwin":
            return OS_MEMORY_OVERHEAD_MACOS_BYTES
    except Exception:
        pass
    return OS_MEMORY_OVERHEAD_LINUX_BYTES
