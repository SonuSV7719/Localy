"""
Pydantic schemas for Hardware Report and Model Fit assessments.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class CPUInfoSchema(BaseModel):
    """Pydantic representation of CPU Topology."""

    brand: str
    architecture: str
    logical_cores: int
    physical_cores: int
    p_cores: int
    e_cores: int
    is_hybrid: bool
    base_clock_mhz: float
    max_clock_mhz: float
    recommended_generation_threads: int
    recommended_batch_threads: int


class GPUInfoSchema(BaseModel):
    """Pydantic representation of GPU Info."""

    device_name: str
    vram_total_mb: int
    usable_for_inference: bool
    backend: str
    driver_version: str = ""
    recommendation: str = ""


class MemoryInfoSchema(BaseModel):
    """Pydantic representation of Memory Info."""

    total_bytes: int
    total_gb: float
    available_bytes: int
    available_gb: float
    swap_total_bytes: int
    swap_free_bytes: int
    has_swap_pressure: bool
    safe_model_budget_bytes: int
    safe_model_budget_gb: float


class StorageInfoSchema(BaseModel):
    """Pydantic representation of Storage Info."""

    free_bytes: int
    free_gb: float
    read_speed_mbps: float
    is_ssd: bool
    mmap_recommended: bool


class InstructionSetSchema(BaseModel):
    """Pydantic representation of SIMD/Instruction Sets."""

    avx: bool
    avx2: bool
    avx512: bool
    fma: bool
    sse4_2: bool
    neon: bool
    best_available_simd: str
    is_optimized: bool


class HardwareReportResponse(BaseModel):
    """Full Hardware Report API response schema."""

    cpu: CPUInfoSchema
    gpu: GPUInfoSchema
    memory: MemoryInfoSchema
    storage: StorageInfoSchema
    instruction_sets: InstructionSetSchema
    timestamp: str
    hardware_hash: str
    summary: str


class FitAssessmentResponse(BaseModel):
    """Model-fit assessment API response schema."""

    model_id: str
    fit_level: str
    explanation: str
    recommendations: list[str]
    max_context: int
    memory_budget_bytes: int
    memory_usage_bytes: int
    headroom_bytes: int
