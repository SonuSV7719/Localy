"""
Unit tests for the hardware-fit advisor.
"""

from __future__ import annotations

from localy.core.constants import FitLevel
from localy.hardware.cpu_topology import CPUTopology
from localy.hardware.gpu_detector import GPUBackend, GPUInfo
from localy.hardware.instruction_sets import InstructionSetReport
from localy.hardware.memory import MemoryInfo
from localy.hardware.report import HardwareReport
from localy.hardware.storage import StorageInfo
from localy.tuning.advisor import assess_model_fit


def test_advisor_fit_scenarios() -> None:
    """Test the fit advisor recommendations across memory budget levels."""
    cpu = CPUTopology(
        brand="Intel Core i5-1235U",
        architecture="x86_64",
        logical_cores=12,
        physical_cores=10,
        p_cores=2,
        e_cores=8,
        is_hybrid=True,
    )
    gpu = GPUInfo(
        device_name="Intel Iris Xe",
        vram_total_mb=128,
        usable_for_inference=False,
        backend=GPUBackend.CPU_ONLY,
    )
    storage = StorageInfo(
        path="C:/models",
        total_bytes=500 * 1024**3,
        free_bytes=100 * 1024**3,
        used_bytes=400 * 1024**3,
        percent_used=80.0,
        read_speed_mbps=500.0,
        is_ssd=True,
        mmap_recommended=True,
    )
    instruction_sets = InstructionSetReport(
        avx2=True,
        best_available_simd="AVX2",
    )

    # Scenario 1: 16GB total RAM -> ~10.4GB budget
    memory_16gb = MemoryInfo(
        total_bytes=16 * 1024**3,
        available_bytes=12 * 1024**3,
        used_bytes=4 * 1024**3,
        percent_used=25.0,
        swap_total_bytes=4 * 1024**3,
        swap_used_bytes=0,
        os_overhead_bytes=3 * 1024**3,
        safe_model_budget_bytes=10 * 1024**3,
    )
    report_16gb = HardwareReport(
        cpu=cpu,
        gpu=gpu,
        memory=memory_16gb,
        storage=storage,
        instruction_sets=instruction_sets,
    )

    # 3B model (SmolLM2 / Llama 3.2 3B) at Q4 should fit well
    fit_3b = assess_model_fit(
        report=report_16gb,
        model_name="Llama-3.2-3B",
        parameter_count_billions=3.0,
        quantization="Q4_K_M",
    )
    assert fit_3b.fit_level == FitLevel.FITS_WELL

    # 8B model (Llama 3.1 8B) at Q4 fits, but is a tight fit
    fit_8b = assess_model_fit(
        report=report_16gb,
        model_name="Llama-3.1-8B",
        parameter_count_billions=8.0,
        quantization="Q4_K_M",
        target_context=16384,
    )
    assert fit_8b.fit_level == FitLevel.FITS_TIGHT

    # 70B model (Llama 3 70B) at Q4 is way too large
    fit_70b = assess_model_fit(
        report=report_16gb,
        model_name="Llama-3-70B",
        parameter_count_billions=70.0,
        quantization="Q4_K_M",
    )
    assert fit_70b.fit_level == FitLevel.DOES_NOT_FIT
    assert any("pooling" in r.lower() for r in fit_70b.recommendations)
