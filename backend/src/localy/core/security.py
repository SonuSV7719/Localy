"""
Localy security — API key auth, localhost binding, rate limiting, CORS.

Security defaults are designed for local-only use:
- Binds to 127.0.0.1 (not 0.0.0.0) — no accidental network exposure
- API key authentication is DISABLED by default
- CORS allows only localhost origins
- When exposed to LAN (Phase 3 pooling), security is tightened automatically
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

if TYPE_CHECKING:
    from localy.core.config import Settings

# API key header scheme — optional by default
_api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def create_api_key_validator(settings: Settings):  # noqa: ANN201
    """Create an API key validation dependency.

    If no API key is configured (default for local use), all requests pass.
    If an API key is set, requests must include it in the Authorization header
    as "Bearer <key>".

    Args:
        settings: Application settings.

    Returns:
        FastAPI dependency function for API key validation.
    """

    async def validate_api_key(
        api_key: str | None = Security(_api_key_header),
    ) -> str | None:
        # No API key configured = no auth required (local use)
        if settings.api_key is None:
            return None

        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required. Set the Authorization header to 'Bearer <your-key>'.",
            )

        # Strip "Bearer " prefix if present
        token = api_key.removeprefix("Bearer ").strip()

        if token != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API key.",
            )

        return token

    return validate_api_key


def is_localhost_only(host: str) -> bool:
    """Check if the server is bound to localhost only.

    Args:
        host: Bind address.

    Returns:
        True if only accessible from localhost.
    """
    return host in {"127.0.0.1", "localhost", "::1"}
