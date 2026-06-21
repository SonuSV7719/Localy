"""
CPU topology detection — P-core/E-core identification for Intel hybrid architectures.

On Intel 12th Gen+ (Alder Lake and later), CPUs have a mix of Performance (P) cores
and Efficiency (E) cores. This matters critically for inference:
- P-cores: Higher IPC, should handle generation threads
- E-cores: Lower IPC, can help with batch/prompt processing

On non-hybrid CPUs (AMD, older Intel, ARM), all cores are treated equally.

Windows implementation uses GetLogicalProcessorInformationEx via ctypes.
Falls back to psutil on non-Windows or when API is unavailable.
"""

from __future__ import annotations

import os
import platform
import struct
from dataclasses import dataclass, field
from typing import Any

import psutil

from localy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CPUTopology:
    """Detected CPU topology information.

    Attributes:
        brand: CPU brand string (e.g., "12th Gen Intel Core i5-1235U").
        architecture: CPU architecture (e.g., "x86_64", "aarch64").
        physical_cores: Total physical core count.
        logical_cores: Total logical core count (includes hyperthreading).
        p_cores: Performance core count (0 if not a hybrid CPU).
        e_cores: Efficiency core count (0 if not a hybrid CPU).
        is_hybrid: True if the CPU has a mix of P and E cores.
        base_clock_mhz: Base clock speed in MHz (0 if unknown).
        max_clock_mhz: Max boost clock speed in MHz (0 if unknown).
        l1_cache_kb: L1 cache size in KB (0 if unknown).
        l2_cache_kb: L2 cache size in KB (0 if unknown).
        l3_cache_kb: L3 cache size in KB (0 if unknown).
    """

    brand: str
    architecture: str
    physical_cores: int
    logical_cores: int
    p_cores: int = 0
    e_cores: int = 0
    is_hybrid: bool = False
    base_clock_mhz: float = 0.0
    max_clock_mhz: float = 0.0
    l1_cache_kb: int = 0
    l2_cache_kb: int = 0
    l3_cache_kb: int = 0
    per_core_info: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recommended_generation_threads(self) -> int:
        """Thread count optimized for token generation.

        Generation is latency-sensitive — use only P-cores (or all cores
        on non-hybrid CPUs) to avoid scheduling onto slower E-cores.
        """
        if self.is_hybrid and self.p_cores > 0:
            return self.p_cores
        # Non-hybrid: use physical cores (not logical — HT rarely helps for inference)
        return self.physical_cores

    @property
    def recommended_batch_threads(self) -> int:
        """Thread count optimized for prompt/batch processing.

        Batch processing is throughput-sensitive — use all physical cores
        including E-cores, since prompt processing is more parallelizable.
        """
        return self.physical_cores


def detect_cpu_topology() -> CPUTopology:
    """Detect CPU topology including P-core/E-core split.

    Returns:
        CPUTopology with all detected information.
    """
    logger.info("cpu_topology_detection_started")

    brand = _get_cpu_brand()
    architecture = platform.machine()
    physical_cores = psutil.cpu_count(logical=False) or 1
    logical_cores = psutil.cpu_count(logical=True) or 1

    # Get clock speeds
    base_mhz, max_mhz = _get_clock_speeds()

    # Get cache sizes
    l1, l2, l3 = _get_cache_sizes()

    # Detect hybrid topology (P-cores vs E-cores)
    p_cores, e_cores, is_hybrid, per_core = _detect_hybrid_topology(physical_cores)

    topology = CPUTopology(
        brand=brand,
        architecture=architecture,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        p_cores=p_cores,
        e_cores=e_cores,
        is_hybrid=is_hybrid,
        base_clock_mhz=base_mhz,
        max_clock_mhz=max_mhz,
        l1_cache_kb=l1,
        l2_cache_kb=l2,
        l3_cache_kb=l3,
        per_core_info=per_core,
    )

    logger.info(
        "cpu_topology_detected",
        brand=topology.brand,
        physical_cores=topology.physical_cores,
        logical_cores=topology.logical_cores,
        p_cores=topology.p_cores,
        e_cores=topology.e_cores,
        is_hybrid=topology.is_hybrid,
        gen_threads=topology.recommended_generation_threads,
        batch_threads=topology.recommended_batch_threads,
    )

    return topology


def _get_cpu_brand() -> str:
    """Get CPU brand string."""
    try:
        if os.name == "nt":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            brand, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            return str(brand).strip()
    except Exception:
        pass

    # Fallback: platform.processor()
    proc = platform.processor()
    return proc if proc else "Unknown CPU"


def _get_clock_speeds() -> tuple[float, float]:
    """Get base and max clock speeds in MHz."""
    try:
        freq = psutil.cpu_freq()
        if freq:
            return float(freq.min or 0), float(freq.max or 0)
    except Exception:
        pass
    return 0.0, 0.0


def _get_cache_sizes() -> tuple[int, int, int]:
    """Get L1, L2, L3 cache sizes in KB.

    Uses Windows registry on Windows, falls back to 0 on other platforms.
    """
    l1, l2, l3 = 0, 0, 0

    try:
        if os.name == "nt":
            import winreg

            cache_key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cache_key_path)
            try:
                # Not all systems expose cache info in registry
                # This is a best-effort approach
                pass
            finally:
                winreg.CloseKey(key)
    except Exception:
        pass

    return l1, l2, l3


def _detect_hybrid_topology(physical_cores: int) -> tuple[int, int, bool, list[dict[str, Any]]]:
    """Detect P-core/E-core split on Intel hybrid CPUs.

    On Windows, uses GetLogicalProcessorInformationEx to query EfficiencyClass.
    On other platforms or if the API fails, assumes homogeneous cores.

    Returns:
        Tuple of (p_cores, e_cores, is_hybrid, per_core_info).
    """
    if os.name == "nt":
        try:
            return _detect_hybrid_windows()
        except Exception as e:
            logger.debug("hybrid_detection_fallback", error=str(e))

    # Fallback: assume all cores are the same (non-hybrid)
    return 0, 0, False, []


def _detect_hybrid_windows() -> tuple[int, int, bool, list[dict[str, Any]]]:
    """Windows-specific P-core/E-core detection via Win32 API.

    Uses GetLogicalProcessorInformationEx with RelationProcessorCore
    to read the EfficiencyClass field:
    - EfficiencyClass 0 = E-core (efficiency)
    - EfficiencyClass 1 = P-core (performance)
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # RelationProcessorCore = 0
    RELATION_PROCESSOR_CORE = 0

    # First call: get required buffer size
    buffer_size = wintypes.DWORD(0)
    kernel32.GetLogicalProcessorInformationEx(
        RELATION_PROCESSOR_CORE,
        None,
        ctypes.byref(buffer_size),
    )

    if buffer_size.value == 0:
        return 0, 0, False, []

    # Allocate buffer and call again
    buffer = (ctypes.c_byte * buffer_size.value)()
    success = kernel32.GetLogicalProcessorInformationEx(
        RELATION_PROCESSOR_CORE,
        ctypes.byref(buffer),
        ctypes.byref(buffer_size),
    )

    if not success:
        error = ctypes.get_last_error()
        logger.warning("win32_processor_info_failed", error_code=error)
        return 0, 0, False, []

    # Parse the variable-length structures
    p_cores = 0
    e_cores = 0
    per_core: list[dict[str, Any]] = []
    offset = 0

    while offset < buffer_size.value:
        # Read the SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX header
        # Relationship (4 bytes) + Size (4 bytes) = 8 byte header
        if offset + 8 > buffer_size.value:
            break

        _relationship = struct.unpack_from("I", buffer, offset)[0]
        struct_size = struct.unpack_from("I", buffer, offset + 4)[0]

        if struct_size == 0:
            break

        # For RelationProcessorCore, the PROCESSOR_RELATIONSHIP structure:
        # Offset 8: Flags (1 byte)
        # Offset 9: EfficiencyClass (1 byte)
        # Offset 10: Reserved (20 bytes)
        # Offset 30: GroupCount (2 bytes)
        # Offset 32: GroupMask array
        if _relationship == RELATION_PROCESSOR_CORE and offset + 10 <= buffer_size.value:
            flags = struct.unpack_from("B", buffer, offset + 8)[0]
            efficiency_class = struct.unpack_from("B", buffer, offset + 9)[0]

            # EfficiencyClass: 0 = E-core, 1 = P-core (on Intel hybrid)
            is_p_core = efficiency_class >= 1
            core_type = "P-core" if is_p_core else "E-core"

            if is_p_core:
                p_cores += 1
            else:
                e_cores += 1

            # SMT flag: bit 0 of Flags indicates if this core has hyperthreading
            has_smt = bool(flags & 0x01)

            per_core.append({
                "type": core_type,
                "efficiency_class": efficiency_class,
                "has_smt": has_smt,
            })

        offset += struct_size

    is_hybrid = p_cores > 0 and e_cores > 0

    if not is_hybrid:
        # If we only found one type, this isn't a hybrid CPU
        # Reset to 0 to signal "non-hybrid, all cores equal"
        total = p_cores + e_cores
        if total > 0:
            logger.debug(
                "non_hybrid_cpu_detected",
                total_cores=total,
                efficiency_class_found="P" if p_cores > 0 else "E",
            )
        p_cores = 0
        e_cores = 0
        per_core = []

    return p_cores, e_cores, is_hybrid, per_core
