"""
Localy constants — magic numbers, defaults, enums, and lookup tables.

All hardcoded values live here, never scattered across the codebase.
When you see a number in inference code, it should trace back to a constant here.
"""

from __future__ import annotations

from enum import Enum


# ===========================
# Application Metadata
# ===========================

APP_NAME = "Localy"
APP_DESCRIPTION = "Fast, accessible local LLM platform with auto-tuned inference."
DEFAULT_PORT = 11434  # Ollama-compatible


# ===========================
# Quantization Tiers
# ===========================

class QuantizationType(str, Enum):
    """GGUF quantization types, ordered by quality (highest to lowest)."""

    F32 = "F32"
    F16 = "F16"
    Q8_0 = "Q8_0"
    Q6_K = "Q6_K"
    Q5_K_M = "Q5_K_M"
    Q5_K_S = "Q5_K_S"
    Q4_K_M = "Q4_K_M"
    Q4_K_S = "Q4_K_S"
    Q3_K_M = "Q3_K_M"
    Q3_K_S = "Q3_K_S"
    Q2_K = "Q2_K"
    IQ4_XS = "IQ4_XS"
    IQ3_XS = "IQ3_XS"
    IQ2_XS = "IQ2_XS"


# Approximate bits-per-weight for each quantization type.
# Used to estimate model memory footprint without downloading.
QUANT_BITS_PER_WEIGHT: dict[QuantizationType, float] = {
    QuantizationType.F32: 32.0,
    QuantizationType.F16: 16.0,
    QuantizationType.Q8_0: 8.5,
    QuantizationType.Q6_K: 6.6,
    QuantizationType.Q5_K_M: 5.7,
    QuantizationType.Q5_K_S: 5.5,
    QuantizationType.Q4_K_M: 4.9,
    QuantizationType.Q4_K_S: 4.6,
    QuantizationType.Q3_K_M: 3.9,
    QuantizationType.Q3_K_S: 3.5,
    QuantizationType.Q2_K: 3.4,
    QuantizationType.IQ4_XS: 4.3,
    QuantizationType.IQ3_XS: 3.3,
    QuantizationType.IQ2_XS: 2.4,
}


# ===========================
# Model Fit Assessment
# ===========================

class FitLevel(str, Enum):
    """How well a model fits on the current hardware."""

    FITS_WELL = "fits_well"        # Loads comfortably, good performance
    FITS_TIGHT = "fits_tight"      # Loads but limited context, marginal perf
    DOES_NOT_FIT = "does_not_fit"  # Needs pooling or smaller quant
    UNKNOWN = "unknown"            # Can't determine (model metadata missing)


# ===========================
# Memory Budget Constants
# ===========================

# OS overhead estimation (bytes). Windows idles at ~2.5–3.5GB, macOS ~2–3GB, Linux ~1–2GB.
OS_MEMORY_OVERHEAD_WINDOWS_BYTES = 3 * 1024**3       # 3 GB
OS_MEMORY_OVERHEAD_MACOS_BYTES = 2.5 * 1024**3       # 2.5 GB
OS_MEMORY_OVERHEAD_LINUX_BYTES = 1.5 * 1024**3       # 1.5 GB

# Application overhead (Python runtime, FastAPI, etc.)
APP_MEMORY_OVERHEAD_BYTES = 512 * 1024**2  # 512 MB

# Safety margin — never use 100% of computed budget
MEMORY_SAFETY_MARGIN = 0.90  # Use at most 90% of computed budget

# KV cache memory per token per layer:
#   For a model with hidden_dim `d` and `n_kv_heads` heads:
#   kv_per_token = 2 * n_kv_heads * head_dim * dtype_size
# These are typical defaults for common architectures.
KV_CACHE_BYTES_PER_TOKEN_7B = 256 * 1024     # ~256 KB per token for 7B models
KV_CACHE_BYTES_PER_TOKEN_13B = 400 * 1024    # ~400 KB per token for 13B models
KV_CACHE_BYTES_PER_TOKEN_70B = 640 * 1024    # ~640 KB per token for 70B models

# Default context lengths to try when computing fit
DEFAULT_CONTEXT_LENGTHS = [2048, 4096, 8192, 16384, 32768]

# Minimum context length — below this, model is essentially unusable
MINIMUM_USABLE_CONTEXT = 512


# ===========================
# Inference Defaults
# ===========================

DEFAULT_BATCH_SIZE = 512
DEFAULT_UBATCH_SIZE = 512
DEFAULT_CONTEXT_LENGTH = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9
DEFAULT_TOP_K = 40
DEFAULT_REPEAT_PENALTY = 1.1
DEFAULT_MAX_TOKENS = 2048

# Speculative decoding defaults
SPECULATIVE_LOOKAHEAD_DEFAULT = 4  # tokens
SPECULATIVE_MIN_ACCEPTANCE_RATE = 0.3  # Disable if below 30% acceptance


# ===========================
# Benchmark Constants
# ===========================

# Standard benchmark prompt (deterministic, reproducible)
BENCHMARK_PROMPT = (
    "Explain the concept of gravitational waves in simple terms. "
    "Cover what causes them, how they were first detected, and why "
    "their discovery was significant for science."
)
BENCHMARK_MAX_TOKENS = 256
BENCHMARK_ITERATIONS = 3  # Median of N iterations
BENCHMARK_WARMUP_TOKENS = 32  # Warmup before timing


# ===========================
# Model Registry
# ===========================

REGISTRY_FILENAME = "model_registry.json"
REGISTRY_UPDATE_URL = "https://raw.githubusercontent.com/localy-ai/localy/main/registry/model_registry.json"
REGISTRY_UPDATE_INTERVAL_HOURS = 24  # Check for updates every 24 hours

# Supported model file extensions
SUPPORTED_MODEL_EXTENSIONS = {".gguf"}


# ===========================
# Network / Pooling (Phase 3)
# ===========================

MDNS_SERVICE_TYPE = "_localy._tcp.local."
POOL_HEALTH_CHECK_INTERVAL_SECONDS = 10
POOL_STALE_THRESHOLD_SECONDS = 30


# ===========================
# Telemetry
# ===========================

TELEMETRY_ENDPOINT = "https://telemetry.localy.ai/v1/report"
TELEMETRY_FLUSH_INTERVAL_SECONDS = 3600  # Report at most once per hour
