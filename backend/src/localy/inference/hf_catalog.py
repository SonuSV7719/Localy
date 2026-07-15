"""
Dynamic model catalog backed by Hugging Face (the official GGUF source).

Instead of hardcoding each model's quantization variants and file sizes, we
fetch them live from the model's HF repo — so the catalog always shows every
available quantization (Q2_K … Q8_0, IQ*, F16 …) with real sizes, and users can
search HF for any GGUF model. Results are cached to disk with a TTL, and every
call degrades gracefully (returns []) when offline so the built-in registry
still works.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from localy.core.logging import get_logger

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 24 * 3600
# Quant tokens as they appear in GGUF filenames, most-specific first.
_QUANT_RE = re.compile(
    r"(IQ\d+_[A-Z]+|Q\d+_K_[A-Z]+|Q\d+_K|Q\d+_\d+|Q\d+_[A-Z]+|Q\d+|BF16|F16|F32)",
    re.IGNORECASE,
)


def parse_quantization(filename: str) -> str | None:
    """Extract the quant label from a GGUF filename, e.g. '...Q4_K_M.gguf' -> 'Q4_K_M'."""
    stem = filename[:-5] if filename.lower().endswith(".gguf") else filename
    matches = _QUANT_RE.findall(stem)
    return matches[-1].upper() if matches else None


class HFCatalog:
    """Fetches GGUF variants and searches models on Hugging Face, with caching."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_file = cache_dir / "hf_variants_cache.json"
        self._mem: dict[str, Any] = {}
        self._load_cache()

    # --- cache ---
    def _load_cache(self) -> None:
        try:
            if self._cache_file.exists():
                self._mem = json.loads(self._cache_file.read_text(encoding="utf-8"))
        except Exception:
            self._mem = {}

    def _save_cache(self) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(self._mem), encoding="utf-8")
        except Exception as e:
            logger.warning("hf_cache_save_failed", error=str(e))

    # --- variants ---
    def fetch_variants(self, repo_id: str, force: bool = False) -> list[dict[str, Any]]:
        """All single-file GGUF variants in a repo: [{quantization, file_size_bytes, huggingface_repo, huggingface_file}]."""
        entry = self._mem.get(repo_id)
        if not force and entry and (time.time() - entry.get("ts", 0)) < _CACHE_TTL_SECONDS:
            return entry["variants"]

        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(repo_id, files_metadata=True)
            by_quant: dict[str, dict[str, Any]] = {}
            for s in info.siblings or []:
                name = s.rfilename
                if not name.lower().endswith(".gguf"):
                    continue
                if "-of-" in name:  # skip multi-part split files (handled separately)
                    continue
                quant = parse_quantization(name)
                if not quant or quant in by_quant:  # first (smallest) wins per quant
                    continue
                by_quant[quant] = {
                    "quantization": quant,
                    "file_size_bytes": int(s.size or 0),
                    "huggingface_repo": repo_id,
                    "huggingface_file": name,
                }
            variants = sorted(by_quant.values(), key=lambda v: v["file_size_bytes"])
            self._mem[repo_id] = {"ts": time.time(), "variants": variants}
            self._save_cache()
            return variants
        except Exception as e:
            logger.warning("hf_fetch_variants_failed", repo=repo_id, error=str(e))
            return entry["variants"] if entry else []  # stale cache or empty

    # --- search ---
    def search_gguf_models(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Hugging Face for GGUF models, most-downloaded first."""
        try:
            from huggingface_hub import HfApi

            models = HfApi().list_models(
                search=query or "gguf",
                filter="gguf",
                sort="downloads",
                limit=limit,
            )
            results = []
            for m in models:
                results.append(
                    {
                        "id": m.id,
                        "downloads": getattr(m, "downloads", 0) or 0,
                        "likes": getattr(m, "likes", 0) or 0,
                    }
                )
            return results
        except Exception as e:
            logger.warning("hf_search_failed", query=query, error=str(e))
            return []
