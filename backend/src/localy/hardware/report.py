"""
Hardware capability report — the master orchestrator.

Runs all sub-probes (CPU, GPU, memory, storage, instruction sets),
aggregates results into a single HardwareReport, and provides both
human-readable and machine-readable output.

This is what the auto-tuning engine and the hardware-fit advisor consume.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localy.core.logging import get_logger
from localy.hardware.cpu_topology import CPUTopology, detect_cpu_topology
from localy.hardware.gpu_detector import GPUInfo, detect_gpu
from localy.hardware.instruction_sets import InstructionSetReport, detect_instruction_sets
from localy.hardware.memory import MemoryInfo, detect_memory
from localy.hardware.storage import StorageInfo, detect_storage

logger = get_logger(__name__)


@dataclass
class HardwareReport:
    """Complete hardware capability report.

    Aggregates all sub-probe results into a single, queryable structure.
    Used by the auto-tuning engine, hardware-fit advisor, and UI.
    """

    cpu: CPUTopology
    gpu: GPUInfo
    memory: MemoryInfo
    storage: StorageInfo
    instruction_sets: InstructionSetReport
    timestamp: str = ""
    hardware_hash: str = ""

    def __post_init__(self) -> None:
        """Compute timestamp and hardware hash after initialization."""
        if not self.timestamp:
            self.timestamp = datetime.now(tz=timezone.utc).isoformat()
        if not self.hardware_hash:
            self.hardware_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute a deterministic hash of hardware configuration.

        Used as a cache key for tuning profiles — if hardware changes,
        the hash changes, and tuning is re-run.
        """
        key_parts = [
            self.cpu.brand,
            str(self.cpu.physical_cores),
            str(self.cpu.logical_cores),
            str(self.cpu.p_cores),
            str(self.cpu.e_cores),
            str(self.memory.total_bytes),
            self.gpu.backend.value,
            self.gpu.device_name,
            str(self.gpu.vram_total_mb),
            self.instruction_sets.best_available_simd,
        ]
        raw = "|".join(key_parts).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    @property
    def summary(self) -> str:
        """Human-readable one-line summary of this hardware."""
        parts = [
            f"CPU: {self.cpu.brand} ({self.cpu.physical_cores} cores",
        ]
        if self.cpu.is_hybrid:
            parts[0] += f", {self.cpu.p_cores}P+{self.cpu.e_cores}E"
        parts[0] += ")"

        parts.append(f"RAM: {self.memory.total_gb:.0f} GB ({self.memory.safe_model_budget_gb:.1f} GB for models)")
        parts.append(f"GPU: {self.gpu.device_name} ({'usable' if self.gpu.usable_for_inference else 'CPU-only'})")
        parts.append(f"SIMD: {self.instruction_sets.best_available_simd}")
        parts.append(f"Storage: {self.storage.free_gb:.0f} GB free")

        return " | ".join(parts)

    @property
    def detailed_report(self) -> str:
        """Multi-line detailed human-readable report."""
        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║              LOCALY HARDWARE CAPABILITY REPORT          ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            "┌─ CPU ─────────────────────────────────────────────────────",
            f"│ Model:          {self.cpu.brand}",
            f"│ Architecture:   {self.cpu.architecture}",
            f"│ Physical Cores: {self.cpu.physical_cores}",
            f"│ Logical Cores:  {self.cpu.logical_cores}",
        ]

        if self.cpu.is_hybrid:
            lines.extend([
                f"│ P-Cores:        {self.cpu.p_cores} (Performance — used for generation)",
                f"│ E-Cores:        {self.cpu.e_cores} (Efficiency — used for batch processing)",
            ])

        if self.cpu.max_clock_mhz > 0:
            lines.append(f"│ Clock Speed:    {self.cpu.base_clock_mhz:.0f} MHz base / {self.cpu.max_clock_mhz:.0f} MHz boost")

        lines.extend([
            f"│ SIMD:           {self.instruction_sets.best_available_simd}",
            f"│ AVX2:           {'✓ Yes' if self.instruction_sets.avx2 else '✗ No'}",
            f"│ AVX-512:        {'✓ Yes' if self.instruction_sets.avx512 else '✗ No'}",
            f"│ Optimized:      {'✓ Yes' if self.instruction_sets.is_optimized else '✗ No (expect slower inference)'}",
            "│",
            "├─ Memory ──────────────────────────────────────────────────",
            f"│ Total RAM:      {self.memory.total_gb:.1f} GB",
            f"│ Available:      {self.memory.available_gb:.1f} GB",
            f"│ Model Budget:   {self.memory.safe_model_budget_gb:.1f} GB (safe for model loading)",
            f"│ Swap Pressure:  {'⚠ Yes — system under memory pressure' if self.memory.has_swap_pressure else '✓ No'}",
            "│",
            "├─ GPU ────────────────────────────────────────────────────",
            f"│ Device:         {self.gpu.device_name}",
            f"│ Backend:        {self.gpu.backend.value}",
            f"│ VRAM:           {self.gpu.vram_total_mb} MB",
            f"│ Usable for LLM: {'✓ Yes' if self.gpu.usable_for_inference else '✗ No — CPU inference only'}",
        ])

        if self.gpu.recommendation:
            lines.append(f"│ Note:           {self.gpu.recommendation[:80]}")

        lines.extend([
            "│",
            "├─ Storage ─────────────────────────────────────────────────",
            f"│ Free Space:     {self.storage.free_gb:.0f} GB",
            f"│ Read Speed:     {self.storage.read_speed_mbps:.0f} MB/s",
            f"│ SSD:            {'✓ Yes' if self.storage.is_ssd else '✗ No (HDD detected)'}",
            f"│ mmap:           {'✓ Recommended' if self.storage.mmap_recommended else '✗ Not recommended'}",
            "│",
            "├─ Inference Recommendation ────────────────────────────────",
        ])

        # Generate inference recommendations based on hardware
        rec = self._generate_recommendations()
        for r in rec:
            lines.append(f"│ • {r}")

        lines.extend([
            "│",
            f"│ Hardware Hash:  {self.hardware_hash}",
            f"│ Probed At:      {self.timestamp}",
            "└───────────────────────────────────────────────────────────",
        ])

        return "\n".join(lines)

    def _generate_recommendations(self) -> list[str]:
        """Generate inference recommendations based on detected hardware."""
        recs = []
        budget_gb = self.memory.safe_model_budget_gb

        if budget_gb >= 12:  # noqa: PLR2004
            recs.append("13B models at Q4_K_M should fit comfortably")
            recs.append("7B models at Q5_K_M or Q8_0 for better quality")
        elif budget_gb >= 6:  # noqa: PLR2004
            recs.append("7B models at Q4_K_M: ✓ Should run well")
            recs.append("7B models at Q8_0: ✓ May fit with reduced context")
            recs.append("13B models: ⚠ Tight fit, consider Q4_K_S or smaller context")
            recs.append("30B+ models: ✗ Won't fit — use device pooling")
        elif budget_gb >= 3:  # noqa: PLR2004
            recs.append("7B models at Q4_K_M: ⚠ Will fit but limited context")
            recs.append("3B models: ✓ Should run well")
            recs.append("13B+ models: ✗ Won't fit — use device pooling")
        else:
            recs.append("⚠ Very limited memory for LLM inference")
            recs.append("1B–3B models only, or use device pooling")

        if not self.instruction_sets.is_optimized:
            recs.append("⚠ No AVX2/NEON — inference will be significantly slower")

        gen_threads = self.cpu.recommended_generation_threads
        batch_threads = self.cpu.recommended_batch_threads
        recs.append(f"Auto-tuned threads: {gen_threads} for generation, {batch_threads} for batch")

        return recs

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (for JSON API responses)."""
        cpu_dict = asdict(self.cpu)
        cpu_dict["recommended_generation_threads"] = self.cpu.recommended_generation_threads
        cpu_dict["recommended_batch_threads"] = self.cpu.recommended_batch_threads

        memory_dict = asdict(self.memory)
        memory_dict["total_gb"] = self.memory.total_gb
        memory_dict["available_gb"] = self.memory.available_gb
        memory_dict["safe_model_budget_gb"] = self.memory.safe_model_budget_gb
        memory_dict["has_swap_pressure"] = self.memory.has_swap_pressure
        memory_dict["swap_free_bytes"] = self.memory.swap_total_bytes - self.memory.swap_used_bytes

        storage_dict = asdict(self.storage)
        storage_dict["free_gb"] = self.storage.free_gb
        storage_dict["total_gb"] = self.storage.total_gb

        is_dict = asdict(self.instruction_sets)
        is_dict["sse4_2"] = self.instruction_sets.sse42
        is_dict["is_optimized"] = self.instruction_sets.is_optimized

        return {
            "cpu": cpu_dict,
            "gpu": asdict(self.gpu),
            "memory": memory_dict,
            "storage": storage_dict,
            "instruction_sets": is_dict,
            "timestamp": self.timestamp,
            "hardware_hash": self.hardware_hash,
            "summary": self.summary,
        }

    def save(self, path: Path) -> None:
        """Save hardware report to a JSON file.

        Args:
            path: File path to save the report to.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        # Convert non-serializable types
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("hardware_report_saved", path=str(path))


def run_full_probe(model_dir: Path) -> HardwareReport:
    """Run all hardware probes and generate a complete report.

    This is the main entry point for hardware detection.
    Results are logged and can be saved/cached for future use.

    Args:
        model_dir: Path where models are stored (for storage probe).

    Returns:
        Complete HardwareReport with all sub-probe results.
    """
    logger.info("full_hardware_probe_started")

    cpu = detect_cpu_topology()
    gpu = detect_gpu()
    memory = detect_memory()
    storage = detect_storage(model_dir)
    instruction_sets = detect_instruction_sets()

    report = HardwareReport(
        cpu=cpu,
        gpu=gpu,
        memory=memory,
        storage=storage,
        instruction_sets=instruction_sets,
    )

    logger.info(
        "full_hardware_probe_completed",
        hardware_hash=report.hardware_hash,
        summary=report.summary,
    )

    return report
