"""
API key store for gated remote access.

Keys let people on the LAN (or over an internet tunnel) call Localy's OpenAI/
Ollama API. Loopback requests from the app itself never need a key; every
non-loopback request must present a valid key (fail-closed).

Keys are stored in {config}/api_keys.json on the user's own machine. This is a
personal local server, so keys are kept in plaintext there (like an .env) — the
security boundary is the machine, and remote access is off unless a key exists.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from threading import Lock
from typing import Any

_KEY_PREFIX = "lk_"


class APIKeyStore:
    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "api_keys.json"
        self._lock = Lock()
        self._keys: dict[str, dict[str, Any]] = {}  # key -> {id, label, created}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._keys = {k["key"]: k for k in data.get("keys", [])}
        except Exception:
            self._keys = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"keys": list(self._keys.values())}, indent=2), encoding="utf-8"
        )

    def generate(self, label: str = "") -> dict[str, Any]:
        with self._lock:
            key = _KEY_PREFIX + secrets.token_urlsafe(24)
            rec = {
                "id": secrets.token_hex(4),
                "key": key,
                "label": label or "API key",
                "created": int(time.time()),
            }
            self._keys[key] = rec
            self._save()
            return rec

    def is_valid(self, key: str | None) -> bool:
        return bool(key) and key in self._keys

    def revoke(self, key_id: str) -> bool:
        with self._lock:
            for k, rec in list(self._keys.items()):
                if rec["id"] == key_id:
                    del self._keys[k]
                    self._save()
                    return True
            return False

    def has_any(self) -> bool:
        return len(self._keys) > 0

    def list_masked(self) -> list[dict[str, Any]]:
        """List keys with the secret masked (safe to show in the UI)."""
        out = []
        for rec in self._keys.values():
            key = rec["key"]
            masked = f"{key[:6]}…{key[-4:]}" if len(key) > 12 else key
            out.append(
                {"id": rec["id"], "label": rec["label"], "created": rec["created"], "masked": masked}
            )
        return sorted(out, key=lambda r: r["created"], reverse=True)


_store: APIKeyStore | None = None


def get_key_store(config_dir: Path) -> APIKeyStore:
    global _store
    if _store is None:
        _store = APIKeyStore(config_dir)
    return _store
