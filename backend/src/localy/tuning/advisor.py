"""
Hardware-fit advisor — honestly tells the user what will and won't work.

This is Section 3, point 3 from the spec: "An honest hardware-fit advisor.
Most current tools let a non-technical person download a model that will
thrash their machine or fail silently, with no warning beforehand."

The advisor computes fit BEFORE download, not after OOM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from localy.core.constants import (
    DEFAULT_CONTEXT_LENGTHS,
    MINIMUM_USABLE_CONTEXT,
    QUANT_BITS_PER_WEIGHT,
    FitLevel,
    QuantizationType,
)
from localy.core.logging import get_logger

if TYPE_CHECKING:
    from localy.hardware.report import HardwareReport

logger = get_logger(__name__)


@dataclass
class FitAssessment:
    """Assessment of whether a model fits on the current hardware.

    Attributes:
        fit_level: Overall fit level (fits_well, fits_tight, does_not_fit).
        model_name: Name of the assessed model.
        model_size_bytes: Estimated model size in bytes.
        max_context: Maximum context length that fits.
        memory_budget_bytes: Available memory budget.
        memory_usage_bytes: Estimated total memory usage (model + KV cache).
        headroom_bytes: Remaining memory after loading (negative = doesn't fit).
        recommendations: List of actionable recommendations.
        explanation: Human-readable explanation of the assessment.
    """

    fit_level: FitLevel
    model_name: str
    model_size_bytes: int
    max_context: int
    memory_budget_bytes: int
    memory_usage_bytes: int
    headroom_bytes: int
    recommendations: list[str] = field(default_factory=list)
    explanation: str = ""


def assess_model_fit(
    report: HardwareReport,
    model_name: str,
    parameter_count_billions: float,
    quantization: QuantizationType | str = QuantizationType.Q4_K_M,
    target_context: int = 4096,
    actual_size_bytes: int | None = None,
) -> FitAssessment:
    """Assess whether a model fits on the current hardware.

    This runs BEFORE download — the user should never download a model
    only to find it doesn't fit.

    Args:
        report: Hardware capability report.
        model_name: Human-readable model name.
        parameter_count_billions: Model parameter count in billions (e.g., 7.0).
        quantization: Quantization type (e.g., Q4_K_M).
        target_context: Desired context length.
        actual_size_bytes: The real on-disk GGUF size for this variant, when
            known (e.g. from the Hugging Face file listing). When provided it is
            used as the weight-memory term instead of the params×quant estimate,
            which makes the assessment exact for the weights — including for
            user-added models whose parameter count can't be parsed from the name.

    Returns:
        FitAssessment with fit level, explanation, and recommendations.
    """
    logger.info(
        "assessing_model_fit",
        model=model_name,
        params_b=parameter_count_billions,
        quant=str(quantization),
        target_ctx=target_context,
        actual_size_bytes=actual_size_bytes,
    )

    # Normalize quantization type
    if isinstance(quantization, str):
        try:
            quant = QuantizationType(quantization)
        except ValueError:
            quant = QuantizationType.Q4_K_M
    else:
        quant = quantization

    bits_per_weight = QUANT_BITS_PER_WEIGHT.get(quant, 4.9)

    # Step 1: Weight memory. Prefer the REAL file size when we have it; fall back
    # to the params×quant estimate only when it's unknown.
    if actual_size_bytes and actual_size_bytes > 0:
        model_size_bytes = int(actual_size_bytes)
    else:
        param_count = int(max(0.0, parameter_count_billions) * 1e9)
        model_size_bytes = int(param_count * bits_per_weight / 8)

    # Step 2: Estimate KV cache size at target context. KV scales with parameter
    # count; if the count is unknown (0 — e.g. an added model with no size token
    # in its name) but we know the real file size, back out an effective param
    # count from size ÷ bits-per-weight so the KV estimate is still sensible.
    effective_params_b = parameter_count_billions
    if effective_params_b <= 0 and model_size_bytes > 0 and bits_per_weight > 0:
        effective_params_b = (model_size_bytes * 8.0 / bits_per_weight) / 1e9

    kv_per_token_bytes = _estimate_kv_per_token(effective_params_b)
    kv_cache_bytes = kv_per_token_bytes * target_context

    # Step 3: Total memory needed
    total_needed = model_size_bytes + kv_cache_bytes

    # Step 4: Compare against budget
    budget = report.memory.safe_model_budget_bytes
    headroom = budget - total_needed

    # Robustness: if we could determine neither a real size nor a parameter
    # count, we cannot honestly claim it fits. Return a cautionary assessment
    # rather than a false green light.
    if model_size_bytes <= 0:
        return FitAssessment(
            fit_level=FitLevel.FITS_TIGHT,
            model_name=model_name,
            model_size_bytes=0,
            max_context=target_context,
            memory_budget_bytes=budget,
            memory_usage_bytes=0,
            headroom_bytes=budget,
            recommendations=["Model size couldn't be determined; fit will be re-checked after download."],
            explanation=(
                f"⚠️ Could not determine {model_name}'s size (no file size or parameter "
                f"count available), so its fit can't be verified up front."
            ),
        )

    # Step 5: Determine fit level
    recommendations: list[str] = []

    if headroom > budget * 0.15:
        # More than 15% headroom = fits well
        fit_level = FitLevel.FITS_WELL
        explanation = (
            f"✅ {model_name} fits well on your device. "
            f"Model needs ~{total_needed / (1024**3):.1f} GB, "
            f"you have ~{budget / (1024**3):.1f} GB available. "
            f"Context length {target_context} is supported."
        )
    elif headroom > 0:
        # Positive but tight headroom
        fit_level = FitLevel.FITS_TIGHT
        max_ctx = _find_max_context(budget, model_size_bytes, kv_per_token_bytes)
        explanation = (
            f"⚠️ {model_name} will fit, but it's tight. "
            f"Model needs ~{total_needed / (1024**3):.1f} GB of your "
            f"~{budget / (1024**3):.1f} GB budget. "
            f"Maximum safe context: {max_ctx} tokens."
        )
        if max_ctx < target_context:
            recommendations.append(
                f"Reduce context from {target_context} to {max_ctx} for stable operation"
            )
        _add_downgrade_recommendations(recommendations, parameter_count_billions, quant)
    else:
        # Doesn't fit
        fit_level = FitLevel.DOES_NOT_FIT
        max_ctx = _find_max_context(budget, model_size_bytes, kv_per_token_bytes)
        explanation = (
            f"🔴 {model_name} does NOT fit on this device. "
            f"Needs ~{total_needed / (1024**3):.1f} GB but only "
            f"~{budget / (1024**3):.1f} GB available."
        )

        _add_downgrade_recommendations(recommendations, parameter_count_billions, quant)
        recommendations.append("Use device pooling to combine memory from multiple devices")

    assessment = FitAssessment(
        fit_level=fit_level,
        model_name=model_name,
        model_size_bytes=model_size_bytes,
        max_context=_find_max_context(budget, model_size_bytes, kv_per_token_bytes),
        memory_budget_bytes=budget,
        memory_usage_bytes=total_needed,
        headroom_bytes=headroom,
        recommendations=recommendations,
        explanation=explanation,
    )

    logger.info(
        "model_fit_assessed",
        model=model_name,
        fit_level=fit_level.value,
        model_size_gb=round(model_size_bytes / (1024**3), 2),
        total_needed_gb=round(total_needed / (1024**3), 2),
        budget_gb=round(budget / (1024**3), 2),
        headroom_gb=round(headroom / (1024**3), 2),
    )

    return assessment


def _estimate_kv_per_token(param_billions: float) -> int:
    """Estimate KV cache bytes per token based on model size.

    These are rough estimates based on common architectures.
    More precise calculation requires actual model metadata.
    """
    if param_billions <= 3:  # noqa: PLR2004
        return 128 * 1024   # 128 KB per token
    if param_billions <= 8:  # noqa: PLR2004
        return 256 * 1024   # 256 KB per token
    if param_billions <= 14:  # noqa: PLR2004
        return 400 * 1024   # 400 KB per token
    if param_billions <= 34:  # noqa: PLR2004
        return 512 * 1024   # 512 KB per token
    return 640 * 1024       # 640 KB per token


def _find_max_context(budget_bytes: int, model_size_bytes: int, kv_per_token: int) -> int:
    """Find the maximum context length that fits in the budget."""
    remaining = budget_bytes - model_size_bytes
    if remaining <= 0 or kv_per_token <= 0:
        return MINIMUM_USABLE_CONTEXT

    max_tokens = remaining // kv_per_token

    # Round down to nearest standard context length
    for ctx in reversed(DEFAULT_CONTEXT_LENGTHS):
        if ctx <= max_tokens:
            return ctx

    return max(MINIMUM_USABLE_CONTEXT, min(max_tokens, MINIMUM_USABLE_CONTEXT))


def _add_downgrade_recommendations(
    recommendations: list[str],
    param_billions: float,
    quant: QuantizationType,
) -> None:
    """Add recommendations for downsizing to fit."""
    # Suggest lower quantization
    quant_order = [
        QuantizationType.Q8_0,
        QuantizationType.Q6_K,
        QuantizationType.Q5_K_M,
        QuantizationType.Q4_K_M,
        QuantizationType.Q4_K_S,
        QuantizationType.Q3_K_M,
        QuantizationType.IQ4_XS,
        QuantizationType.IQ3_XS,
    ]

    current_idx = None
    for i, q in enumerate(quant_order):
        if q == quant:
            current_idx = i
            break

    if current_idx is not None and current_idx < len(quant_order) - 1:
        next_quant = quant_order[current_idx + 1]
        recommendations.append(f"Try {next_quant.value} quantization (smaller, slightly lower quality)")

    # Suggest smaller model
    if param_billions > 7:  # noqa: PLR2004
        recommendations.append("Try a 7B model instead — runs well on most hardware")
    elif param_billions > 3:  # noqa: PLR2004
        recommendations.append("Try a 3B model for faster, lower-memory inference")
