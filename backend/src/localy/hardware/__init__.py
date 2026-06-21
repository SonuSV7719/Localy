"""
Master hardware probe entry point.

Convenience re-exports for the hardware detection package.
"""

from localy.hardware.cpu_topology import CPUTopology, detect_cpu_topology
from localy.hardware.gpu_detector import GPUBackend, GPUInfo, detect_gpu
from localy.hardware.instruction_sets import InstructionSetReport, detect_instruction_sets
from localy.hardware.memory import MemoryInfo, detect_memory
from localy.hardware.report import HardwareReport, run_full_probe
from localy.hardware.storage import StorageInfo, detect_storage

__all__ = [
    "CPUTopology",
    "GPUBackend",
    "GPUInfo",
    "HardwareReport",
    "InstructionSetReport",
    "MemoryInfo",
    "StorageInfo",
    "detect_cpu_topology",
    "detect_gpu",
    "detect_instruction_sets",
    "detect_memory",
    "detect_storage",
    "run_full_probe",
]
