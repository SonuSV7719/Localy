"""
GPU detection — identify available GPU backends for inference acceleration.

Detection priority order:
1. CUDA (NVIDIA) — best supported, most models optimize for it
2. ROCm (AMD) — growing support in llama.cpp
3. Metal (macOS) — Apple Silicon, excellent performance
4. Vulkan — cross-vendor, increasingly supported
5. OpenCL — legacy, limited use for LLMs
6. CPU-only — fallback when no usable GPU found

IMPORTANT: Intel Iris Xe (integrated, 128MB) is detected but explicitly flagged
as NOT usable for LLM inference. This is honest, not a limitation — 128MB of
shared memory cannot meaningfully accelerate model inference.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum

from localy.core.logging import get_logger

logger = get_logger(__name__)


class GPUBackend(str, Enum):
    """Available GPU compute backends."""

    CUDA = "cuda"
    ROCM = "rocm"
    METAL = "metal"
    VULKAN = "vulkan"
    OPENCL = "opencl"
    CPU_ONLY = "cpu_only"


@dataclass(frozen=True)
class GPUInfo:
    """Detected GPU information.

    Attributes:
        backend: The GPU backend available (or CPU_ONLY).
        device_name: GPU device name (e.g., "NVIDIA GeForce RTX 4090").
        vram_total_mb: Total dedicated VRAM in MB (0 for integrated/CPU-only).
        vram_available_mb: Available VRAM in MB.
        compute_capability: CUDA compute capability (e.g., "8.6"). Empty for non-CUDA.
        driver_version: GPU driver version string.
        usable_for_inference: Whether this GPU is realistically usable for LLM inference.
        recommendation: Human-readable recommendation about this GPU.
    """

    backend: GPUBackend
    device_name: str = "None"
    vram_total_mb: int = 0
    vram_available_mb: int = 0
    compute_capability: str = ""
    driver_version: str = ""
    usable_for_inference: bool = False
    recommendation: str = ""

    @property
    def recommended_gpu_layers(self) -> int:
        """Estimate how many model layers can be offloaded to this GPU.

        Returns 0 if GPU is not usable for inference.
        Very rough estimate — actual depends on model architecture.
        """
        if not self.usable_for_inference or self.vram_available_mb < 512:
            return 0

        # Rough: ~100MB per layer for 7B models, ~200MB for 13B
        # This is a conservative estimate; actual varies by model
        return max(1, self.vram_available_mb // 150)


def detect_gpu() -> GPUInfo:
    """Detect GPU capabilities for inference acceleration.

    Checks backends in priority order and returns the best available option.
    Returns GPUInfo with backend=CPU_ONLY if nothing usable is found.

    Returns:
        GPUInfo describing the best available GPU backend.
    """
    logger.info("gpu_detection_started")

    # 1. Check CUDA (NVIDIA)
    cuda_info = _detect_cuda()
    if cuda_info is not None:
        logger.info("gpu_detected", **_gpu_to_log_dict(cuda_info))
        return cuda_info

    # 2. Check ROCm (AMD)
    rocm_info = _detect_rocm()
    if rocm_info is not None:
        logger.info("gpu_detected", **_gpu_to_log_dict(rocm_info))
        return rocm_info

    # 3. Check Metal (macOS)
    metal_info = _detect_metal()
    if metal_info is not None:
        logger.info("gpu_detected", **_gpu_to_log_dict(metal_info))
        return metal_info

    # 4. Check Vulkan
    vulkan_info = _detect_vulkan()
    if vulkan_info is not None:
        logger.info("gpu_detected", **_gpu_to_log_dict(vulkan_info))
        return vulkan_info

    # 5. Fallback: CPU-only
    cpu_only = GPUInfo(
        backend=GPUBackend.CPU_ONLY,
        device_name="None (CPU-only inference)",
        usable_for_inference=False,
        recommendation=(
            "No discrete GPU detected. Inference will use CPU only. "
            "This is perfectly fine for 7B models — expect ~5-15 tok/s depending on your CPU. "
            "For larger models, consider device pooling (Phase 3)."
        ),
    )
    logger.info("gpu_not_found", recommendation=cpu_only.recommendation)
    return cpu_only


def _detect_cuda() -> GPUInfo | None:
    """Detect NVIDIA GPU via nvidia-smi."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None

    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.free,compute_cap,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            return None

        line = result.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:  # noqa: PLR2004
            return None

        name, vram_total, vram_free, compute_cap, driver = parts

        vram_total_mb = int(float(vram_total))
        vram_free_mb = int(float(vram_free))

        # CUDA is usable if we have meaningful VRAM (at least 2GB)
        usable = vram_total_mb >= 2048

        recommendation = (
            f"NVIDIA {name} with {vram_total_mb}MB VRAM detected. "
            f"{'Suitable for GPU-accelerated inference.' if usable else 'VRAM too low for meaningful GPU offload.'}"
        )

        return GPUInfo(
            backend=GPUBackend.CUDA,
            device_name=name,
            vram_total_mb=vram_total_mb,
            vram_available_mb=vram_free_mb,
            compute_capability=compute_cap,
            driver_version=driver,
            usable_for_inference=usable,
            recommendation=recommendation,
        )

    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError) as e:
        logger.debug("cuda_detection_failed", error=str(e))
        return None


def _detect_rocm() -> GPUInfo | None:
    """Detect AMD GPU via rocm-smi."""
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi is None:
        return None

    try:
        result = subprocess.run(
            [rocm_smi, "--showproductname", "--showmeminfo", "vram"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            return None

        # Parse ROCm output (format varies by version)
        device_name = "AMD GPU"
        for line in result.stdout.split("\n"):
            if "Card" in line and "series" in line.lower():
                device_name = line.split(":")[-1].strip()
                break

        return GPUInfo(
            backend=GPUBackend.ROCM,
            device_name=device_name,
            usable_for_inference=True,
            recommendation=f"AMD {device_name} detected with ROCm support.",
        )

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("rocm_detection_failed", error=str(e))
        return None


def _detect_metal() -> GPUInfo | None:
    """Detect Apple Metal (macOS only)."""
    if platform.system() != "Darwin":
        return None

    try:
        # On macOS, Metal is always available on supported hardware
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        # Check if Apple Silicon (unified memory = great for LLMs)
        is_apple_silicon = "Apple" in result.stdout

        # Get total memory (on Apple Silicon, GPU shares system RAM)
        mem_result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        total_mem_mb = int(mem_result.stdout.strip()) // (1024 * 1024) if mem_result.returncode == 0 else 0

        # Apple Silicon can use ~75% of system RAM for GPU
        gpu_usable_mb = int(total_mem_mb * 0.75) if is_apple_silicon else 0

        return GPUInfo(
            backend=GPUBackend.METAL,
            device_name="Apple Silicon GPU" if is_apple_silicon else "Apple Metal GPU",
            vram_total_mb=gpu_usable_mb,
            vram_available_mb=gpu_usable_mb,
            usable_for_inference=is_apple_silicon,
            recommendation=(
                f"Apple Silicon with Metal detected. {gpu_usable_mb}MB unified memory available for GPU inference. "
                "Excellent for local LLM inference."
                if is_apple_silicon
                else "Intel Mac with Metal detected. CPU inference recommended."
            ),
        )

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("metal_detection_failed", error=str(e))
        return None


def _detect_vulkan() -> GPUInfo | None:
    """Detect Vulkan-capable GPU.

    On Windows, checks for Intel Iris Xe but flags it as NOT usable.
    """
    # On Windows, check for Intel integrated GPU
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
            )
            device_desc, _ = winreg.QueryValueEx(key, "DriverDesc")
            winreg.CloseKey(key)

            device_name = str(device_desc)

            # Intel Iris Xe detection — be HONEST about its (lack of) capability
            if "intel" in device_name.lower() and ("iris" in device_name.lower() or "uhd" in device_name.lower()):
                return GPUInfo(
                    backend=GPUBackend.VULKAN,
                    device_name=device_name,
                    vram_total_mb=128,  # Typical Intel Iris Xe dedicated
                    vram_available_mb=128,
                    usable_for_inference=False,
                    recommendation=(
                        f"{device_name} detected (integrated GPU, ~128MB dedicated). "
                        "This GPU does NOT have enough VRAM for LLM inference — "
                        "128MB of shared memory cannot meaningfully accelerate model loading. "
                        "Inference will use CPU only, which is the correct choice for this hardware. "
                        "For GPU-accelerated inference, a discrete GPU with 4GB+ VRAM is needed."
                    ),
                )

        except Exception:
            pass

    # Generic Vulkan detection via vulkaninfo
    vulkaninfo = shutil.which("vulkaninfo")
    if vulkaninfo is None:
        return None

    try:
        result = subprocess.run(
            [vulkaninfo, "--summary"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode == 0 and "deviceName" in result.stdout:
            for line in result.stdout.split("\n"):
                if "deviceName" in line:
                    device_name = line.split("=")[-1].strip()
                    return GPUInfo(
                        backend=GPUBackend.VULKAN,
                        device_name=device_name,
                        usable_for_inference=True,
                        recommendation=f"Vulkan GPU detected: {device_name}.",
                    )

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _gpu_to_log_dict(gpu: GPUInfo) -> dict[str, object]:
    """Convert GPUInfo to a dict for structured logging."""
    return {
        "backend": gpu.backend.value,
        "device": gpu.device_name,
        "vram_mb": gpu.vram_total_mb,
        "usable": gpu.usable_for_inference,
    }
