from __future__ import annotations

import threading
import time
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, "src")

from localy.pooling.coordinator import Coordinator
from localy.pooling.pool_state import PoolState
from localy.pooling.shard_planner import PoolNode, ShardPlan
from localy.core.exceptions import PoolingError
from localy.services.pool_service import PoolService


class _CoordinatorStub:
    is_ready = False
    is_running = False
    model_id = "test:1b"
    proxy_url = "http://127.0.0.1:8080"

    def progress(self) -> dict:
        return {"phase": "loading", "active": True}


def _service_with_state(state: PoolState) -> PoolService:
    service = object.__new__(PoolService)
    service._state = state
    service._members = {}
    service._members_lock = threading.Lock()
    service._coordinator = _CoordinatorStub()
    service._worker = None
    service._events = deque()
    return service


def test_status_keeps_joined_offline_worker_visible() -> None:
    state = PoolState()
    state.set_local(
        PoolNode(
            node_id="local",
            host="local",
            port=0,
            budget_bytes=8 * 1024**3,
            is_local=True,
            label="This device",
        )
    )
    service = _service_with_state(state)
    offline = PoolNode(
        node_id="192.168.1.50:50052",
        host="192.168.1.50",
        port=50052,
        budget_bytes=4 * 1024**3,
        label="Phone",
    )
    service._members[offline.node_id] = offline

    status = service.status()

    phone = next(n for n in status["nodes"] if n["node_id"] == offline.node_id)
    assert phone["online"] is False
    assert status["node_count"] == 2
    assert status["remote_count"] == 1
    assert status["offline_count"] == 1
    assert status["total_budget_gb"] == 8.0


def test_join_rejects_unreachable_worker() -> None:
    state = PoolState()
    state.set_local(PoolNode("local", "local", 0, 8 * 1024**3, is_local=True, label="This device"))
    service = _service_with_state(state)
    service._probe_worker = lambda _host, _port, _metrics_port, _timeout: False

    try:
        service.join("192.0.2.10", 50052, label="Offline")
    except PoolingError as e:
        assert "Cannot reach worker" in str(e)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unreachable worker was joined")

    assert service.status()["remote_count"] == 0


def test_operations_uses_serialized_layer_shares() -> None:
    state = PoolState()
    local = PoolNode("local", "local", 0, 8 * 1024**3, is_local=True, label="This device")
    remote = PoolNode("pc:50052", "pc", 50052, 8 * 1024**3, label="Second PC")
    state.set_local(local)
    state.upsert(remote)
    service = _service_with_state(state)
    service._members[remote.node_id] = remote

    service.plan_for_model = lambda _model: ShardPlan(
        fits=True,
        model_size_bytes=10 * 1024**3,
        required_bytes=12 * 1024**3,
        total_budget_bytes=16 * 1024**3,
        nodes=[local, remote],
        tensor_split=[0.4, 0.6],
        reason="fits",
    )

    operations = service.operations()

    shares = {n["node_id"]: n["planned_layer_share_pct"] for n in operations["status"]["nodes"]}
    assert shares["local"] == 40.0
    assert shares["pc:50052"] == 60.0
    assert operations["model_size_bytes"] == 10 * 1024**3


def test_coordinator_estimates_transfer_without_worker_metrics() -> None:
    coordinator = Coordinator(SimpleNamespace(coordinator_port=8080))
    with coordinator._lock:
        coordinator._phase = "loading"
        coordinator._model_id = "test:1b"
        coordinator._started_at = time.time() - 10
        coordinator._last_log_at = time.time()
        coordinator._progress_frac = 0.605
        coordinator._bytes_total = 1024**3
        coordinator._node_count = 2
        coordinator._remote_count = 1

    progress = coordinator.progress()

    assert progress["transfer_measurement"] == "estimated_from_loader"
    assert progress["bytes_is_estimate"] is True
    assert progress["bytes_sent"] is not None
    assert 0 < progress["bytes_sent"] < progress["bytes_total"]
    assert progress["speed_bps"] is not None


def test_coordinator_ignores_control_bytes_before_real_transfer() -> None:
    coordinator = Coordinator(SimpleNamespace(coordinator_port=8080))
    with coordinator._lock:
        coordinator._phase = "starting"
        coordinator._model_id = "test:1b"
        coordinator._started_at = time.time() - 30
        coordinator._last_log_at = time.time()
        coordinator._bytes_total = 512 * 1024**2
        coordinator._observed_bytes = 64 * 1024
        coordinator._metric_samples.append((time.time() - 10, 32 * 1024))
        coordinator._metric_samples.append((time.time(), 64 * 1024))
        coordinator._node_count = 2
        coordinator._remote_count = 1

    progress = coordinator.progress()

    assert progress["transfer_measurement"] == "not_available"
    assert progress["bytes_sent"] is None
    assert progress["speed_bps"] is None
    assert progress["eta_s"] is None


def test_coordinator_clamps_observed_transfer_to_planned_bytes() -> None:
    coordinator = Coordinator(SimpleNamespace(coordinator_port=8080))
    with coordinator._lock:
        coordinator._phase = "loading"
        coordinator._model_id = "test:1b"
        coordinator._started_at = time.time() - 30
        coordinator._last_log_at = time.time()
        coordinator._bytes_total = 256 * 1024**2
        coordinator._observed_bytes = 512 * 1024**2
        coordinator._metric_samples.append((time.time() - 10, 128 * 1024**2))
        coordinator._metric_samples.append((time.time(), 512 * 1024**2))
        coordinator._last_transfer_at = time.time()
        coordinator._node_count = 2
        coordinator._remote_count = 1

    progress = coordinator.progress()

    assert progress["transfer_measurement"] == "observed_network"
    assert progress["bytes_sent"] == progress["bytes_total"]
    assert progress["eta_s"] == 0.0


def test_coordinator_treats_fit_failure_log_as_fatal() -> None:
    coordinator = Coordinator(SimpleNamespace(coordinator_port=8080))
    with coordinator._lock:
        coordinator._phase = "loading"
        coordinator._model_id = "test:1b"
        coordinator._started_at = time.time() - 5

    coordinator._ingest_line(
        "0.02.809.460 W common_fit_params: failed to fit params to free device memory: "
        "n_gpu_layers already set by user to 999, abort"
    )
    progress = coordinator.progress()

    assert progress["phase"] == "error"
    assert progress["active"] is False
    assert "could not fit the pooled model" in progress["error"]
    assert "failed to fit params" in progress["error"]


def test_coordinator_load_lets_llama_fit_gpu_layers() -> None:
    coordinator = Coordinator(SimpleNamespace(coordinator_port=8080))
    local = PoolNode("local", "local", 0, 8 * 1024**3, is_local=True, label="This device")
    remote = PoolNode("phone:50052", "phone", 50052, 2 * 1024**3, label="Phone")
    plan = ShardPlan(
        fits=True,
        model_size_bytes=1024**3,
        required_bytes=int(1024**3 * 1.2),
        total_budget_bytes=10 * 1024**3,
        nodes=[local, remote],
        tensor_split=[0.7, 0.3],
        reason="fits",
    )
    commands: list[list[str]] = []

    class FakeProc:
        stdout = []

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(cmd: list[str], **_kwargs: object) -> FakeProc:
        commands.append(cmd)
        return FakeProc()

    with (
        patch("localy.pooling.coordinator.llama_server_path", return_value=Path(__file__)),
        patch.object(Coordinator, "_verify_rpc_workers", return_value=None),
        patch("localy.pooling.coordinator.subprocess.Popen", side_effect=fake_popen),
    ):
        coordinator.start("test:1b", __file__, plan, n_ctx=512, ready_timeout=0.01)
        coordinator.stop()

    cmd = commands[0]
    assert "-ngl" not in cmd
    assert "--gpu-layers" not in cmd
    assert "--fit" in cmd
    assert cmd[cmd.index("--fit") + 1] == "on"


def test_coordinator_stop_clears_transfer_progress() -> None:
    coordinator = Coordinator(SimpleNamespace(coordinator_port=8080))
    with coordinator._lock:
        coordinator._phase = "ready"
        coordinator._ready = True
        coordinator._model_id = "test:1b"
        coordinator._started_at = time.time() - 10
        coordinator._ready_at = time.time()
        coordinator._progress_frac = 1.0
        coordinator._bytes_total = 1024**3
        coordinator._observed_bytes = 512 * 1024**2
        coordinator._node_count = 3
        coordinator._remote_count = 2
        coordinator._last_log = "server is listening"

    coordinator.stop()
    progress = coordinator.progress()

    assert progress["phase"] == "idle"
    assert progress["model"] is None
    assert progress["bytes_total"] is None
    assert progress["bytes_sent"] is None
    assert progress["node_count"] == 0
    assert progress["remote_count"] == 0
