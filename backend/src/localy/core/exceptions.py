"""
Localy custom exception hierarchy.

All exceptions inherit from LocalyError and carry:
- A human-readable message (for UI/logs)
- An error code (for API responses and traceability)
- Optional details dict (for structured context)

Error codes follow the pattern: LOCALY_{DOMAIN}_{SPECIFIC}
This makes it trivial to grep logs or API responses for a specific failure class.
"""

from __future__ import annotations

from typing import Any


class LocalyError(Exception):
    """Base exception for all Localy errors.

    Attributes:
        message: Human-readable error description.
        error_code: Machine-parseable error code (e.g., LOCALY_MODEL_NOT_FOUND).
        details: Optional structured context for debugging.
    """

    error_code: str = "LOCALY_UNKNOWN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API error responses."""
        result: dict[str, Any] = {
            "error": {
                "code": self.error_code,
                "message": self.message,
            },
        }
        if self.details:
            result["error"]["details"] = self.details
        return result


# ===========================
# Hardware Errors
# ===========================


class HardwareProbeError(LocalyError):
    """Failed to detect hardware capabilities."""

    error_code = "LOCALY_HARDWARE_PROBE_FAILED"


class InsufficientMemoryError(LocalyError):
    """Not enough RAM for the requested operation."""

    error_code = "LOCALY_INSUFFICIENT_MEMORY"


class InsufficientStorageError(LocalyError):
    """Not enough disk space for model download/storage."""

    error_code = "LOCALY_INSUFFICIENT_STORAGE"


# ===========================
# Model Errors
# ===========================


class ModelNotFoundError(LocalyError):
    """Requested model is not in the registry or not downloaded."""

    error_code = "LOCALY_MODEL_NOT_FOUND"


class ModelTooLargeError(LocalyError):
    """Model exceeds available memory for this device.

    This is the core "honest hardware-fit advisor" exception.
    It should include recommendations (e.g., try a smaller quant, use pooling).
    """

    error_code = "LOCALY_MODEL_TOO_LARGE"


class ModelCorruptedError(LocalyError):
    """Model file failed integrity verification (SHA256 mismatch)."""

    error_code = "LOCALY_MODEL_CORRUPTED"


class ModelLoadError(LocalyError):
    """Failed to load model into inference engine."""

    error_code = "LOCALY_MODEL_LOAD_FAILED"


class ModelAlreadyLoadedError(LocalyError):
    """A different model is already loaded. Unload first."""

    error_code = "LOCALY_MODEL_ALREADY_LOADED"


# ===========================
# Inference Errors
# ===========================


class InferenceError(LocalyError):
    """Error during inference (token generation)."""

    error_code = "LOCALY_INFERENCE_ERROR"


class InferenceTimeoutError(LocalyError):
    """Inference took too long (context too large, model too slow)."""

    error_code = "LOCALY_INFERENCE_TIMEOUT"


class NoModelLoadedError(LocalyError):
    """No model is currently loaded. Load one first."""

    error_code = "LOCALY_NO_MODEL_LOADED"


# ===========================
# Download Errors
# ===========================


class DownloadError(LocalyError):
    """Failed to download model file."""

    error_code = "LOCALY_DOWNLOAD_FAILED"


class DownloadCancelledError(LocalyError):
    """Download was cancelled by user."""

    error_code = "LOCALY_DOWNLOAD_CANCELLED"


class RegistryUpdateError(LocalyError):
    """Failed to update model registry from remote."""

    error_code = "LOCALY_REGISTRY_UPDATE_FAILED"


# ===========================
# Configuration Errors
# ===========================


class ConfigurationError(LocalyError):
    """Invalid configuration."""

    error_code = "LOCALY_CONFIGURATION_ERROR"


# ===========================
# Pooling Errors (Phase 3)
# ===========================


class PoolingError(LocalyError):
    """Error in device pooling."""

    error_code = "LOCALY_POOLING_ERROR"


class DeviceNotReachableError(PoolingError):
    """Cannot reach a pooled device."""

    error_code = "LOCALY_DEVICE_NOT_REACHABLE"


class ClusterFormationError(PoolingError):
    """Failed to form a device cluster."""

    error_code = "LOCALY_CLUSTER_FORMATION_FAILED"


# ===========================
# Benchmark Errors
# ===========================


class BenchmarkError(LocalyError):
    """Error during benchmarking."""

    error_code = "LOCALY_BENCHMARK_ERROR"
