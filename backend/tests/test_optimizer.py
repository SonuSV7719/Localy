"""
Unit tests for the auto-tuning optimizer.
"""

from __future__ import annotations

from localy.core.config import TuningProfile
from localy.hardware.cpu_topology import CPUTopology
from localy.hardware.gpu_detector import GPUBackend, GPUInfo
from localy.hardware.instruction_sets import InstructionSetReport
from localy.hardware.memory import MemoryInfo
from localy.hardware.report import HardwareReport
from localy.hardware.storage import StorageInfo
from localy.tuning.optimizer import compute_inference_config


def test_optimizer_balanced_profile() -> None:
    """Test optimizer with a balanced profile on typical hardware."""
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
    memory = MemoryInfo(
        total_bytes=16 * 1024**3,
        available_bytes=10 * 1024**3,
        used_bytes=6 * 1024**3,
        percent_used=37.5,
        swap_total_bytes=4 * 1024**3,
        swap_used_bytes=0,
        os_overhead_bytes=3 * 1024**3,
        safe_model_budget_bytes=10 * 1024**3,
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

    report = HardwareReport(
        cpu=cpu,
        gpu=gpu,
        memory=memory,
        storage=storage,
        instruction_sets=instruction_sets,
    )

    # 4.9GB model (llama 3 8b q4_k_m)
    model_size = int(4.9 * 1024**3)

    config = compute_inference_config(
        report=report,
        model_size_bytes=model_size,
        profile=TuningProfile.BALANCED,
    )

    # Gen threads should favor P-cores (2)
    assert config.n_threads == 2
    # Batch threads should use physical cores (10)
    assert config.n_threads_batch == 10
    # Batch size defaults to 512 in balanced
    assert config.n_batch == 512
    # use_mmap should match storage recommendation
    assert config.use_mmap is True
    # CPU only means 0 GPU layers offloaded
    assert config.n_gpu_layers == 0
