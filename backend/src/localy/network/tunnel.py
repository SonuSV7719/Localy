"""
Expose the local API to the internet via a Cloudflare Quick Tunnel.

Quick tunnels need no Cloudflare account: `cloudflared tunnel --url <local>`
prints a public https://<random>.trycloudflare.com URL that forwards to our
server. Combined with API-key auth, remote users with a valid key can reach the
model from anywhere. (Quick-tunnel URLs are ephemeral and rate-limited — good
for sharing with friends, not heavy production traffic.)
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from localy.core.config import Settings
from localy.core.exceptions import LocalyError
from localy.core.logging import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_EXE = ".exe" if os.name == "nt" else ""
_CF_NAME = f"cloudflared{_EXE}"

if os.name == "nt":
    _CREATE_NO_WINDOW = 0x08000000
else:
    _CREATE_NO_WINDOW = 0


def cloudflared_path(settings: Settings) -> Path | None:
    """Locate the cloudflared binary (bundled resource or vendored)."""
    candidates: list[Path] = []
    if settings.llama_bin_dir is not None:
        base = Path(settings.llama_bin_dir)
        candidates += [base / _CF_NAME, base.parent / "cloudflared" / _CF_NAME]
    backend_root = Path(__file__).resolve().parents[3]
    candidates.append(backend_root / "vendor" / "cloudflared" / _CF_NAME)
    for c in candidates:
        if c.exists():
            return c
    return None


class TunnelManager:
    """Manages a single cloudflared quick-tunnel subprocess."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._proc: subprocess.Popen | None = None
        self._url: str | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def url(self) -> str | None:
        return self._url if self.running else None

    def start(self, port: int, timeout: float = 40.0) -> dict:
        if self.running:
            return {"running": True, "url": self._url}

        binary = cloudflared_path(self._settings)
        if binary is None:
            raise LocalyError(
                "cloudflared not found. It ships with Localy; reinstall, or place "
                "cloudflared.exe next to the RPC binaries.",
                error_code="LOCALY_TUNNEL_NO_BINARY",
            )

        cmd = [
            str(binary),
            "tunnel",
            "--url",
            f"http://127.0.0.1:{port}",
            "--no-autoupdate",
        ]
        logger.info("starting_tunnel", cmd=" ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(binary.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=_CREATE_NO_WINDOW,
        )

        # cloudflared prints the public URL to its output within a few seconds.
        self._url = None
        deadline = time.time() + timeout
        assert self._proc.stdout is not None
        while time.time() < deadline and self.running:
            line = self._proc.stdout.readline()
            if not line:
                if self._proc.poll() is not None:
                    break
                continue
            m = _URL_RE.search(line)
            if m:
                self._url = m.group(0)
                break

        # Keep draining output so the pipe buffer never blocks cloudflared.
        threading.Thread(target=self._drain, daemon=True).start()

        if not self._url:
            self.stop()
            raise LocalyError(
                "Tunnel did not come up in time. Check your internet connection and try again.",
                error_code="LOCALY_TUNNEL_TIMEOUT",
            )
        logger.info("tunnel_ready", url=self._url)
        return {"running": True, "url": self._url}

    def _drain(self) -> None:
        try:
            if self._proc and self._proc.stdout:
                for _ in self._proc.stdout:
                    pass
        except Exception:
            pass

    def stop(self) -> dict:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._url = None
        return {"running": False}

    def status(self) -> dict:
        return {"running": self.running, "url": self.url}


_manager: TunnelManager | None = None


def get_tunnel_manager(settings: Settings) -> TunnelManager:
    global _manager
    if _manager is None:
        _manager = TunnelManager(settings)
    return _manager
