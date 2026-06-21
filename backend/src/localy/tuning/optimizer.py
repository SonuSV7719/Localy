"""
Auto-tuning optimizer — computes optimal inference parameters from hardware.

This is the core differentiator vs Ollama (generic defaults) and LM Studio (manual sliders).
Every parameter is computed from actual hardware measurements, not guessed.

The optimizer produces an InferenceConfig that is passed directly to llama-cpp-python.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from localy.core.config import TuningProfile
from localy.core.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CONTEXT_LENGTH,
    MINIMUM_USABLE_CONTEXT,
)
from localy.core.logging import get_logger

if TYPE_CHECKING:
    from localy.hardware.report import HardwareReport

logger = get_logger(__name__)


@dataclass
class InferenceConfig:
    """Computed inference configuration for llama-cpp-python.

    Every field maps directly to a llama.cpp parameter.
    None means "use llama.cpp's own default."
    """

    # Threading
    n_threads: int = 4          # Generation threads (P-cores preferred)
    n_threads_batch: int = 4    # Batch/prompt processing threads (all cores)

    # Batch processing
    n_batch: int = 512          # Prompt processing batch size
    n_ubatch: int = 512         # Physical batch size

    # Context
    n_ctx: int = 4096           # Context window size

    # GPU offloading
    n_gpu_layers: int = 0       # Layers to offload to GPU (0 = CPU only)

    # Memory mapping
    use_mmap: bool = True       # Use memory-mapped model loading
    use_mlock: bool = False     # Lock model in RAM (prevents swapping)

    # Attention
    flash_attn: bool = False    # Flash attention (GPU only)

    # Performance metadata (not passed to llama.cpp, for UI display)
    tuning_profile: str = "balanced"
    tuning_notes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.tuning_notes is None:
            self.tuning_notes = []


def compute_inference_config(
    report: HardwareReport,
    model_size_bytes: int = 0,
    requested_context: int | None = None,
    profile: TuningProfile = TuningProfile.BALANCED,
    *,
    thread_override: int | None = None,
    batch_override: int | None = None,
) -> InferenceConfig:
    """Compute optimal inference parameters from hardware report.

    This is the brain of the auto-tuning engine. Every parameter is
    derived from actual hardware measurements, not hardcoded.

    Args:
        report: Hardware capability report from the probe.
        model_size_bytes: Size of the model file (0 if unknown).
        requested_context: User-requested context length (None = auto).
        profile: Tuning aggressiveness (conservative/balanced/aggressive).
        thread_override: Explicit thread count override (power user).
        batch_override: Explicit batch size override (power user).

    Returns:
        InferenceConfig with all computed parameters.
    """
    logger.info("computing_inference_config", profile=profile.value, model_size_bytes=model_size_bytes)

    notes: list[str] = []

    # --- Thread Count ---
    if thread_override is not None:
        n_threads = thread_override
        n_threads_batch = thread_override
        notes.append(f"Thread count overridden to {thread_override}")
    else:
        n_threads, n_threads_batch = _compute_threads(report, profile)

    # --- Batch Size ---
    if batch_override is not None:
        n_batch = batch_override
        notes.append(f"Batch size overridden to {batch_override}")
    else:
        n_batch = _compute_batch_size(report, profile)

    # --- Context Length ---
    n_ctx = _compute_context_length(
        report=report,
        model_size_bytes=model_size_bytes,
        requested_context=requested_context,
        profile=profile,
    )

    # --- GPU Layers ---
    n_gpu_layers = _compute_gpu_layers(report, model_size_bytes)

    # --- Memory Mapping ---
    use_mmap = report.storage.mmap_recommended
    if not use_mmap:
        notes.append("mmap disabled — slow storage or limited disk space detected")

    # mlock: Lock model in RAM on aggressive profile to prevent swapping
    use_mlock = profile == TuningProfile.AGGRESSIVE

    # --- Flash Attention ---
    flash_attn = report.gpu.usable_for_inference and n_gpu_layers > 0

    config = InferenceConfig(
        n_threads=n_threads,
        n_threads_batch=n_threads_batch,
        n_batch=n_batch,
        n_ubatch=min(n_batch, 512),
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        use_mmap=use_mmap,
        use_mlock=use_mlock,
        flash_attn=flash_attn,
        tuning_profile=profile.value,
        tuning_notes=notes,
    )

    logger.info(
        "inference_config_computed",
        n_threads=config.n_threads,
        n_threads_batch=config.n_threads_batch,
        n_batch=config.n_batch,
        n_ctx=config.n_ctx,
        n_gpu_layers=config.n_gpu_layers,
        use_mmap=config.use_mmap,
        profile=config.tuning_profile,
    )

    return config


def _compute_threads(report: HardwareReport, profile: TuningProfile) -> tuple[int, int]:
    """Compute optimal thread counts for generation and batch processing.

    Key insight: on hybrid CPUs (Intel 12th Gen+), generation should use only
    P-cores (latency-sensitive), while batch processing can use all cores.

    Returns:
        Tuple of (generation_threads, batch_threads).
    """
    cpu = report.cpu
    gen_threads = cpu.recommended_generation_threads
    batch_threads = cpu.recommended_batch_threads

    # Apply profile adjustments
    if profile == TuningProfile.CONSERVATIVE:
        # Leave 1-2 cores free for OS responsiveness
        gen_threads = max(1, gen_threads - 1)
        batch_threads = max(1, batch_threads - 2)
    elif profile == TuningProfile.AGGRESSIVE:
        # Use all available cores including logical (hyperthreaded)
        gen_threads = cpu.logical_cores if not cpu.is_hybrid else gen_threads
        batch_threads = cpu.logical_cores

    return max(1, gen_threads), max(1, batch_threads)


def _compute_batch_size(report: HardwareReport, profile: TuningProfile) -> int:
    """Compute optimal batch size based on available memory."""
    budget_gb = report.memory.safe_model_budget_gb

    if profile == TuningProfile.CONSERVATIVE:
        if budget_gb < 6:  # noqa: PLR2004
            return 256
        return 512

    if profile == TuningProfile.AGGRESSIVE:
        if budget_gb >= 12:  # noqa: PLR2004
            return 1024
        return 512

    # Balanced
    if budget_gb < 4:  # noqa: PLR2004
        return 256
    return DEFAULT_BATCH_SIZE


def _compute_context_length(
    report: HardwareReport,
    model_size_bytes: int,
    requested_context: int | None,
    profile: TuningProfile,
) -> int:
    """Compute maximum safe context length.

    Context length directly affects memory usage via the KV cache.
    We compute the maximum context that fits within the memory budget
    after the model is loaded.
    """
    budget_bytes = report.memory.safe_model_budget_bytes

    if model_size_bytes > 0:
        # Remaining bytes after model loading
        remaining = budget_bytes - model_size_bytes
    else:
        # No model size known — assume 50% of budget for model, 50% for context
        remaining = budget_bytes // 2

    # Profile-based headroom
    if profile == TuningProfile.CONSERVATIVE:
        remaining = int(remaining * 0.7)
    elif profile == TuningProfile.AGGRESSIVE:
        remaining = int(remaining * 0.95)
    else:
        remaining = int(remaining * 0.85)

    # Estimate KV cache per token (~256KB for 7B models is a rough average)
    kv_per_token = 256 * 1024  # 256 KB — conservative estimate
    max_context = max(MINIMUM_USABLE_CONTEXT, remaining // kv_per_token) if remaining > 0 else MINIMUM_USABLE_CONTEXT

    # Cap at reasonable maximum
    max_context = min(max_context, 32768)

    # If user requested a specific context, use it (but warn if it might not fit)
    if requested_context is not None:
        if requested_context > max_context:
            logger.warning(
                "requested_context_exceeds_budget",
                requested=requested_context,
                computed_max=max_context,
                msg="Requested context may cause memory pressure",
            )
        return requested_context

    # Default: pick the largest standard context that fits
    standard_contexts = [2048, 4096, 8192, 16384, 32768]
    for ctx in reversed(standard_contexts):
        if ctx <= max_context:
            return ctx

    return DEFAULT_CONTEXT_LENGTH


def _compute_gpu_layers(report: HardwareReport, model_size_bytes: int) -> int:
    """Compute number of model layers to offload to GPU.

    Returns 0 if GPU is not usable for inference.
    """
    if not report.gpu.usable_for_inference:
        return 0

    return report.gpu.recommended_gpu_layers
