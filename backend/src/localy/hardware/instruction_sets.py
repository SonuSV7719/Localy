"""
CPU instruction set detection — AVX2, AVX-512, SSE4.2, NEON, FMA.

Instruction set support determines which llama.cpp binary optimizations
are available. AVX2 is the critical threshold for good CPU inference on x86.
AVX-512 provides additional speedup where available.

Uses the `cpufeature` library for reliable detection.
"""

from __future__ import annotations

from dataclasses import dataclass

from localy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class InstructionSetReport:
    """Detected CPU instruction set capabilities.

    Attributes:
        sse42: SSE 4.2 support (baseline for modern x86).
        avx: AVX support.
        avx2: AVX2 support (critical for good llama.cpp performance).
        avx512: AVX-512 support (additional speedup).
        fma: Fused Multiply-Add support.
        neon: ARM NEON support (ARM-based CPUs).
        best_available_simd: The best SIMD instruction set available.
    """

    sse42: bool = False
    avx: bool = False
    avx2: bool = False
    avx512: bool = False
    fma: bool = False
    neon: bool = False
    best_available_simd: str = "none"

    @property
    def is_optimized(self) -> bool:
        """Whether the CPU supports at least AVX2 (or NEON on ARM).

        AVX2 is the practical minimum for good CPU inference performance
        with llama.cpp. Without it, inference is significantly slower.
        """
        return self.avx2 or self.neon


def detect_instruction_sets() -> InstructionSetReport:
    """Detect available CPU instruction sets.

    Returns:
        InstructionSetReport with all detected capabilities.
    """
    logger.info("instruction_set_detection_started")

    sse42 = False
    avx = False
    avx2 = False
    avx512 = False
    fma = False
    neon = False
    best_simd = "none"

    try:
        import cpufeature

        features = cpufeature.CPUFeature

        sse42 = bool(getattr(features, "SSE4_2", False) or getattr(features, "SSE42", False))
        avx = bool(getattr(features, "AVX", False))
        avx2 = bool(getattr(features, "AVX2", False))
        fma = bool(getattr(features, "FMA", False) or getattr(features, "FMA3", False))

        # AVX-512 has multiple sub-extensions
        avx512 = bool(
            getattr(features, "AVX512F", False)
            or getattr(features, "AVX512f", False)
        )

        # Determine best SIMD level
        if avx512:
            best_simd = "AVX-512"
        elif avx2:
            best_simd = "AVX2"
        elif avx:
            best_simd = "AVX"
        elif sse42:
            best_simd = "SSE4.2"

    except ImportError:
        logger.warning("cpufeature_not_available", msg="Install cpufeature for instruction set detection")

        # Fallback: try platform detection for ARM NEON
        import platform

        machine = platform.machine().lower()
        if machine in {"aarch64", "arm64"}:
            neon = True
            best_simd = "NEON"

    except Exception as e:
        logger.warning("instruction_set_detection_failed", error=str(e))

    report = InstructionSetReport(
        sse42=sse42,
        avx=avx,
        avx2=avx2,
        avx512=avx512,
        fma=fma,
        neon=neon,
        best_available_simd=best_simd,
    )

    logger.info(
        "instruction_sets_detected",
        best_simd=report.best_available_simd,
        avx2=report.avx2,
        avx512=report.avx512,
        is_optimized=report.is_optimized,
    )

    return report
