"""
Localy configuration — all application settings managed via pydantic-settings.

Settings are loaded from (in priority order):
1. Environment variables (prefixed with LOCALY_)
2. .env file in the backend directory
3. Default values defined here

Usage:
    from localy.core.config import get_settings
    settings = get_settings()
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


class LogFormat(str, Enum):
    """Logging output format."""

    CONSOLE = "console"
    JSON = "json"


class TuningProfile(str, Enum):
    """Inference tuning aggressiveness."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


def _default_data_dir() -> Path:
    """Platform-aware default data directory."""
    if os.name == "nt":
        # Windows: %LOCALAPPDATA%\Localy
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif os.uname().sysname == "Darwin":  # type: ignore[union-attr]
        # macOS: ~/Library/Application Support/Localy
        base = Path.home() / "Library" / "Application Support"
    else:
        # Linux: ~/.local/share/localy
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Localy"


class Settings(BaseSettings):
    """Application-wide configuration.

    All settings can be overridden via environment variables prefixed with LOCALY_.
    Example: LOCALY_PORT=8080 overrides the port setting.
    """

    model_config = SettingsConfigDict(
        env_prefix="LOCALY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Server ---
    host: str = Field(
        default="127.0.0.1",
        description="Server bind address. Default 127.0.0.1 = localhost only (secure).",
    )
    port: int = Field(
        default=11434,
        ge=1024,
        le=65535,
        description="Server port. Default 11434 matches Ollama for compatibility.",
    )

    # --- Paths ---
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        description="Root data directory for all Localy files.",
    )
    model_dir: Path | None = Field(
        default=None,
        description="Model storage directory. Defaults to {data_dir}/models.",
    )

    # --- Logging ---
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    log_format: LogFormat = Field(
        default=LogFormat.CONSOLE,
        description="Log format: 'console' for dev, 'json' for production.",
    )

    # --- Inference Defaults ---
    default_context_length: int = Field(
        default=4096,
        ge=512,
        le=131072,
        description="Default context window size in tokens.",
    )
    default_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Default sampling temperature.",
    )
    default_top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Default nucleus sampling probability.",
    )

    # --- Tuning ---
    tuning_profile: TuningProfile = Field(
        default=TuningProfile.BALANCED,
        description="Inference tuning profile: conservative, balanced, aggressive.",
    )
    thread_count_override: int | None = Field(
        default=None,
        ge=1,
        description="Override auto-detected thread count. None = auto.",
    )
    batch_size_override: int | None = Field(
        default=None,
        ge=1,
        description="Override auto-detected batch size. None = auto.",
    )
    use_mmap: bool = Field(
        default=True,
        description="Use memory-mapped model loading (recommended).",
    )

    # --- Pooling (Phase 3) ---
    llama_bin_dir: Path | None = Field(
        default=None,
        description=(
            "Directory containing the RPC-enabled rpc-server / llama-server "
            "binaries (built via scripts/build-llama-rpc). "
            "Defaults to <repo>/backend/vendor/llama-rpc if present."
        ),
    )
    rpc_port: int = Field(
        default=50052,
        ge=1024,
        le=65535,
        description="Port the local rpc-server worker listens on.",
    )
    rpc_bind_host: str = Field(
        default="0.0.0.0",
        description="Bind address for the rpc-server worker (0.0.0.0 to accept LAN peers).",
    )
    coordinator_port: int = Field(
        default=8080,
        ge=1024,
        le=65535,
        description="Port for the local llama-server coordinator that pooled mode proxies to.",
    )
    pool_enabled: bool = Field(
        default=False,
        description="Enable device pooling features. Off by default; solo mode always works.",
    )

    # --- Security ---
    api_key: str | None = Field(
        default=None,
        description="API key for authentication. None = no auth (default for local use).",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:*", "http://127.0.0.1:*", "tauri://localhost"],
        description="Allowed CORS origins.",
    )

    # --- Telemetry (opt-in) ---
    telemetry_enabled: bool = Field(
        default=False,
        description="Enable anonymous telemetry. Disabled by default.",
    )

    # --- Computed Properties ---
    @property
    def models_path(self) -> Path:
        """Resolved model storage directory."""
        if self.model_dir is not None:
            return self.model_dir
        return self.data_dir / "models"

    @property
    def config_path(self) -> Path:
        """Configuration file storage directory."""
        return self.data_dir / "config"

    @property
    def benchmarks_path(self) -> Path:
        """Benchmark results storage directory."""
        return self.data_dir / "benchmarks"

    @property
    def logs_path(self) -> Path:
        """Log files directory."""
        return self.data_dir / "logs"

    @property
    def cache_path(self) -> Path:
        """Cache directory (tuning cache, etc.)."""
        return self.data_dir / "cache"

    # --- Validators ---
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Normalize log level to uppercase."""
        v = v.upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in valid:
            msg = f"Invalid log level '{v}'. Must be one of: {', '.join(sorted(valid))}"
            raise ValueError(msg)
        return v

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        for path in [
            self.data_dir,
            self.models_path,
            self.config_path,
            self.benchmarks_path,
            self.logs_path,
            self.cache_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings (singleton).

    Returns:
        The global Settings instance. Cached after first call.
    """
    settings = Settings()
    settings.ensure_directories()
    return settings
