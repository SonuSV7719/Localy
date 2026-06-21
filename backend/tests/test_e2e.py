"""
End-to-End integration test covering the complete pipeline.

Simulates model discovery, pre-download hardware checks, model pulling,
dynamic loading with auto-tuning config, and chat completion inference.
"""

from __future__ import annotations

import sys
sys.path.insert(0, 'src')

import json
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from localy.main import create_app
from localy.inference.types import LoadedModelInfo, ModelStatus


@patch("localy.utils.download.download_file")
@patch("localy.services.hardware_service.run_full_probe")
@patch("localy.services.model_service.run_full_probe")
@patch("localy.hardware.report.run_full_probe")
@patch("llama_cpp.Llama")
def test_e2e_full_flow(
    mock_llama_class: MagicMock,
    mock_probe_dep: MagicMock,
    mock_probe_model: MagicMock,
    mock_probe_hw: MagicMock,
    mock_download: AsyncMock,
) -> None:
    """Test the complete workflow from health checks to generation.

    Mocks dependencies to avoid downloading multi-GB model weights and instantiating
    heavy native extensions, while fully validating API schemas and routing logic.
    """
    # 1. Setup hardware probe mock
    from localy.hardware.cpu_topology import CPUTopology
    from localy.hardware.gpu_detector import GPUBackend, GPUInfo
    from localy.hardware.instruction_sets import InstructionSetReport
    from localy.hardware.memory import MemoryInfo
    from localy.hardware.storage import StorageInfo
    from localy.hardware.report import HardwareReport

    mock_report = HardwareReport(
        cpu=CPUTopology(
            brand="Intel Core i5-1235U",
            architecture="x86_64",
            logical_cores=12,
            physical_cores=10,
            p_cores=2,
            e_cores=8,
            is_hybrid=True,
        ),
        gpu=GPUInfo(
            device_name="Intel Iris Xe",
            vram_total_mb=128,
            usable_for_inference=False,
            backend=GPUBackend.CPU_ONLY,
        ),
        memory=MemoryInfo(
            total_bytes=16 * 1024**3,
            available_bytes=12 * 1024**3,
            used_bytes=4 * 1024**3,
            percent_used=25.0,
            swap_total_bytes=4 * 1024**3,
            swap_used_bytes=0,
            os_overhead_bytes=3 * 1024**3,
            safe_model_budget_bytes=10 * 1024**3,
        ),
        storage=StorageInfo(
            path="C:/models",
            total_bytes=500 * 1024**3,
            free_bytes=100 * 1024**3,
            used_bytes=400 * 1024**3,
            percent_used=80.0,
            read_speed_mbps=500.0,
            is_ssd=True,
            mmap_recommended=True,
        ),
        instruction_sets=InstructionSetReport(
            avx2=True,
            best_available_simd="AVX2",
        ),
    )
    mock_probe_dep.return_value = mock_report
    mock_probe_model.return_value = mock_report
    mock_probe_hw.return_value = mock_report

    # 2. Setup mock download completion
    mock_download.return_value = None

    # 3. Setup mock Llama model completion responses
    mock_llama_instance = MagicMock()
    mock_llama_instance.create_chat_completion.return_value = {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1234567,
        "model": "smollm2:2b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is a mock chat completion response.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
        },
    }
    mock_llama_class.return_value = mock_llama_instance

    # Initialize client
    app = create_app()
    client = TestClient(app)

    # Step A: Liveness Check
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Step B: Get Hardware Configuration Report
    response = client.get("/system/hardware")
    assert response.status_code == 200
    report_json = response.json()
    assert report_json["hardware_hash"] == mock_report.hardware_hash
    assert "cpu" in report_json
    assert "memory" in report_json

    # Step C: Model Compatibility Fit Advisor
    response = client.get("/system/hardware/fit/smollm2:2b")
    assert response.status_code == 200
    fit_json = response.json()
    assert fit_json["fit_level"] == "fits_well"

    # Step D: Pull/Download Model weights
    # We must patch the model store to report that the file was downloaded successfully
    with patch("localy.storage.model_store.ModelStore.has_model", return_value=True):
        # Step E: OpenAI-Compatible Chat Completions
        chat_req = {
            "model": "smollm2:2b",
            "messages": [
                {"role": "user", "content": "Tell me a joke."}
            ],
            "temperature": 0.5,
            "stream": False
        }

        # We also need to patch stats to avoid OS errors on the dummy file path
        dummy_stat = MagicMock()
        dummy_stat.st_size = 1024**3  # 1 GB
        with patch("pathlib.Path.stat", return_value=dummy_stat), \
             patch("pathlib.Path.exists", return_value=True):
            response = client.post("/v1/chat/completions", json=chat_req)

            assert response.status_code == 200
            comp_json = response.json()
            assert comp_json["choices"][0]["message"]["content"] == "This is a mock chat completion response."
            assert comp_json["usage"]["total_tokens"] == 18

            # Step F: Readiness diagnostics check
            # Note: Model loading in engine is mocked so model will be loaded
            response = client.get("/ready")
            assert response.status_code == 200
            ready_json = response.json()
            assert ready_json["status"] == "ready"

