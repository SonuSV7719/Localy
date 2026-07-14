"""
Locate the RPC-enabled llama.cpp binaries used for pooled inference.

These are NOT the `llama-cpp-python` wheel (which has no RPC support). They are
standalone `rpc-server` and `llama-server` executables built from source with
`-DGGML_RPC=ON` via `scripts/build-llama-rpc.bat`, landing in
`backend/vendor/llama-rpc/`.
"""

from __future__ import annotations

import os
from pathlib import Path

from localy.core.config import Settings
from localy.core.exceptions import PoolingError
from localy.core.logging import get_logger

logger = get_logger(__name__)

# ggml-rpc-server.exe / llama-server.exe on Windows; no extension on POSIX.
# (The RPC worker target is named `ggml-rpc-server` in current llama.cpp.)
_EXE = ".exe" if os.name == "nt" else ""
RPC_SERVER_NAME = f"ggml-rpc-server{_EXE}"
LLAMA_SERVER_NAME = f"llama-server{_EXE}"


def default_bin_dir() -> Path:
    """The conventional build output dir: <backend>/vendor/llama-rpc."""
    # .../backend/src/localy/pooling/binaries.py -> parents[3] == backend
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "vendor" / "llama-rpc"


def resolve_bin_dir(settings: Settings) -> Path:
    """Resolve where the pooling binaries live (config override or default)."""
    return settings.llama_bin_dir if settings.llama_bin_dir is not None else default_bin_dir()


def find_binary(name: str, settings: Settings) -> Path:
    """Return the path to a required pooling binary, or raise PoolingError."""
    path = resolve_bin_dir(settings) / name
    if not path.exists():
        raise PoolingError(
            f"Required pooling binary '{name}' not found at {path}. "
            f"Build it first: run scripts/build-llama-rpc.bat from the repo root.",
            details={"expected_path": str(path)},
        )
    return path


def rpc_server_path(settings: Settings) -> Path:
    """Path to the rpc-server worker binary."""
    return find_binary(RPC_SERVER_NAME, settings)


def llama_server_path(settings: Settings) -> Path:
    """Path to the llama-server coordinator binary."""
    return find_binary(LLAMA_SERVER_NAME, settings)


def binaries_available(settings: Settings) -> bool:
    """True if both pooling binaries are present (non-raising check)."""
    bin_dir = resolve_bin_dir(settings)
    return (bin_dir / RPC_SERVER_NAME).exists() and (bin_dir / LLAMA_SERVER_NAME).exists()
