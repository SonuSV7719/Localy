"""
SHA256 hashing utilities for model file integrity verification.

Handles multi-GB files with streaming hash computation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from localy.core.logging import get_logger

logger = get_logger(__name__)


def compute_file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA256 hash of a file.

    Uses streaming reads to handle multi-GB files without loading into memory.

    Args:
        path: Path to the file.
        chunk_size: Read chunk size in bytes (default 1MB).

    Returns:
        Hex-encoded SHA256 hash string.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

    digest = hasher.hexdigest()
    logger.debug("file_hash_computed", path=str(path), sha256=digest[:16] + "...")
    return digest


def verify_file_integrity(path: Path, expected_sha256: str) -> bool:
    """Verify file integrity against expected SHA256 hash.

    Args:
        path: Path to the file.
        expected_sha256: Expected SHA256 hash.

    Returns:
        True if hash matches, False otherwise.
    """
    if not path.exists():
        logger.warning("file_not_found_for_verification", path=str(path))
        return False

    actual = compute_file_sha256(path)
    matches = actual == expected_sha256

    if not matches:
        logger.error(
            "file_integrity_check_failed",
            path=str(path),
            expected=expected_sha256[:16] + "...",
            actual=actual[:16] + "...",
        )

    return matches


def compute_string_hash(content: str) -> str:
    """Compute SHA256 hash of a string.

    Useful for generating cache keys from model names, configs, etc.

    Args:
        content: String to hash.

    Returns:
        Hex-encoded SHA256 hash (first 16 characters for brevity).
    """
    return hashlib.sha256(content.encode()).hexdigest()[:16]
