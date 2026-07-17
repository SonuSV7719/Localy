"""
mDNS/zeroconf discovery for pool workers (Phase 3, Stage 2).

Workers advertise a `_localy._tcp.local.` service carrying their rpc-server port
and offered memory. Coordinators browse for these and auto-populate the pool, so
friends on the same WiFi/hotspot appear with zero manual IP entry.

Discovery is optional: manual `pool join host:port` works without it. If the
`zeroconf` package is unavailable, this module degrades to no-ops.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Callable

from localy.core.constants import MDNS_API_SERVICE_TYPE, MDNS_SERVICE_TYPE
from localy.core.logging import get_logger

logger = get_logger(__name__)

try:
    from zeroconf import ServiceInfo, Zeroconf
    from zeroconf import ServiceBrowser, ServiceListener

    _ZEROCONF_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _ZEROCONF_AVAILABLE = False
    ServiceListener = object  # type: ignore


@dataclass
class DiscoveredWorker:
    node_id: str
    host: str
    port: int
    label: str
    budget_bytes: int
    compute_score: float = 1.0


def _local_ip() -> str:
    """Best-effort primary LAN IP of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks the route's iface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class WorkerAdvertiser:
    """Advertises this device as a pool worker over mDNS."""

    def __init__(self, port: int, label: str, budget_bytes: int, compute_score: float = 1.0) -> None:
        self._port = port
        self._label = label
        self._budget = budget_bytes
        self._compute = compute_score
        self._zc: "Zeroconf | None" = None
        self._info: "ServiceInfo | None" = None

    def start(self) -> None:
        if not _ZEROCONF_AVAILABLE:
            logger.warning("zeroconf_unavailable_skipping_advertise")
            return
        ip = _local_ip()
        hostname = socket.gethostname()
        name = f"{hostname}-{self._port}.{MDNS_SERVICE_TYPE}"
        self._info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            name,
            addresses=[socket.inet_aton(ip)],
            port=self._port,
            properties={
                "label": self._label or hostname,
                "budget": str(self._budget),
                "compute": str(self._compute),
                "node_id": f"{ip}:{self._port}",
            },
        )
        self._zc = Zeroconf()
        self._zc.register_service(self._info)
        logger.info("worker_advertised", name=name, ip=ip, port=self._port)

    def stop(self) -> None:
        if self._zc and self._info:
            try:
                self._zc.unregister_service(self._info)
            finally:
                self._zc.close()
        self._zc = None
        self._info = None


class ServerAdvertiser:
    """Advertises the Localy API server over mDNS so LAN client apps (e.g. the
    Android chat screen) can auto-discover the PC's host:port. Auth is still a
    per-request API key — discovery only removes the need to type the IP."""

    def __init__(self, port: int, label: str = "") -> None:
        self._port = port
        self._label = label
        self._zc: "Zeroconf | None" = None
        self._info: "ServiceInfo | None" = None

    def start(self) -> None:
        if not _ZEROCONF_AVAILABLE:
            logger.warning("zeroconf_unavailable_skipping_server_advertise")
            return
        ip = _local_ip()
        hostname = socket.gethostname()
        name = f"{hostname}.{MDNS_API_SERVICE_TYPE}"
        self._info = ServiceInfo(
            MDNS_API_SERVICE_TYPE,
            name,
            addresses=[socket.inet_aton(ip)],
            port=self._port,
            properties={
                "label": self._label or hostname,
                "host": ip,
                "api": "openai",  # OpenAI-compatible chat at /v1/chat/completions
            },
        )
        try:
            self._zc = Zeroconf()
            self._zc.register_service(self._info)
            logger.info("api_server_advertised", name=name, ip=ip, port=self._port)
        except Exception as e:  # pragma: no cover - mDNS best-effort
            logger.warning("api_server_advertise_failed", error=str(e))
            self._zc = None

    def stop(self) -> None:
        if self._zc and self._info:
            try:
                self._zc.unregister_service(self._info)
            finally:
                self._zc.close()
        self._zc = None
        self._info = None


class _PoolListener(ServiceListener):  # type: ignore[misc]
    def __init__(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self.workers: dict[str, DiscoveredWorker] = {}

    def _resolve(self, zc, type_, name) -> None:
        info = zc.get_service_info(type_, name)
        if not info or not info.addresses:
            return
        ip = socket.inet_ntoa(info.addresses[0])
        props = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in (info.properties or {}).items()
        }
        node_id = props.get("node_id", f"{ip}:{info.port}")
        try:
            compute = float(props.get("compute", "1") or 1)
        except ValueError:
            compute = 1.0
        self.workers[name] = DiscoveredWorker(
            node_id=node_id,
            host=ip,
            port=info.port,
            label=props.get("label", node_id),
            budget_bytes=int(props.get("budget", "0") or 0),
            compute_score=compute,
        )
        self._on_change()

    def add_service(self, zc, type_, name) -> None:
        self._resolve(zc, type_, name)

    def update_service(self, zc, type_, name) -> None:
        self._resolve(zc, type_, name)

    def remove_service(self, zc, type_, name) -> None:
        self.workers.pop(name, None)
        self._on_change()


class WorkerDiscovery:
    """Browses the LAN for advertised pool workers."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._zc: "Zeroconf | None" = None
        self._browser: "ServiceBrowser | None" = None
        self._listener: _PoolListener | None = None
        self._on_change = on_change or (lambda: None)

    def start(self) -> None:
        if not _ZEROCONF_AVAILABLE:
            logger.warning("zeroconf_unavailable_skipping_discovery")
            return
        self._zc = Zeroconf()
        self._listener = _PoolListener(self._on_change)
        self._browser = ServiceBrowser(self._zc, MDNS_SERVICE_TYPE, self._listener)
        logger.info("discovery_started", service=MDNS_SERVICE_TYPE)

    def list_workers(self) -> list[DiscoveredWorker]:
        if self._listener is None:
            return []
        return list(self._listener.workers.values())

    def stop(self) -> None:
        if self._zc:
            self._zc.close()
        self._zc = None
        self._browser = None
        self._listener = None
