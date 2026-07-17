"""
Localy Model Service.

Provides a high-level service layer for listing, fetching, downloading, verifying,
and loading GGUF models with optimal configurations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from localy.core.config import Settings
from localy.core.exceptions import ModelNotFoundError
from localy.core.logging import get_logger
from localy.hardware.report import run_full_probe
from localy.inference.engine import get_engine
from localy.inference.model_manager import ModelManager
from localy.tuning.advisor import assess_model_fit
from localy.tuning.optimizer import compute_inference_config

if TYPE_CHECKING:
    from localy.storage.model_store import ModelStore
    from localy.inference.types import LoadedModelInfo

logger = get_logger(__name__)


class ModelService:
    """Manages the lifecycle and scheduling of models."""

    def __init__(self, settings: Settings, store: ModelStore) -> None:
        self._settings = settings
        self._store = store
        self._manager = ModelManager(settings, store)
        from localy.inference.hf_catalog import HFCatalog

        self._hf = HFCatalog(settings.cache_path)

    def _resolve_variants(self, entry: Any, dynamic: bool) -> list[tuple[str, Any]]:
        """Return [(quant, variant-like)] — dynamically from HF when possible, else built-in.

        A variant-like has .file_size_bytes and .huggingface_file (the built-in
        QuantVariant, or a light shim built from HF metadata).
        """
        builtin = list(entry.variants.items())
        if not dynamic:
            return builtin
        repo = next((v.huggingface_repo for _, v in builtin if v.huggingface_repo), "")
        if not repo:
            return builtin
        hf_variants = self._hf.fetch_variants(repo)
        if not hf_variants:
            return builtin  # offline / not cached -> built-in

        class _V:  # duck-typed to match QuantVariant fields used below
            def __init__(self, d: dict[str, Any]) -> None:
                self.file_size_bytes = d["file_size_bytes"]
                self.huggingface_file = d["huggingface_file"]
                self.huggingface_repo = d["huggingface_repo"]

        return [(d["quantization"], _V(d)) for d in hf_variants]

    def search_catalog(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Hugging Face for GGUF models to add to the catalog."""
        return self._hf.search_gguf_models(query, limit=limit)

    def add_hf_model(self, repo_id: str) -> dict[str, Any]:
        """Add a Hugging Face GGUF repo to the catalog (variants fetched dynamically)."""
        import re as _re

        from localy.inference.model_registry import ModelEntry, QuantVariant

        variants = self._hf.fetch_variants(repo_id, force=True)
        if not variants:
            raise ModelNotFoundError(
                f"No downloadable GGUF variants found in '{repo_id}'.",
                details={"repo": repo_id},
            )

        short = repo_id.split("/")[-1]
        # Infer parameter count from the repo name, e.g. "...-7B-..." -> 7.0.
        m = _re.search(r"(\d+(?:\.\d+)?)\s*[bB]\b", short)
        params = float(m.group(1)) if m else 0.0
        name = _re.sub(r"[-_.]?(GGUF|gguf)$", "", short)
        name = _re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "model"
        family = name.split("-")[0]

        variant_map = {
            v["quantization"]: QuantVariant(
                quantization=v["quantization"],
                file_size_bytes=v["file_size_bytes"],
                huggingface_repo=v["huggingface_repo"],
                huggingface_file=v["huggingface_file"],
                sha256="",
                download_url="",
            )
            for v in variants
        }
        default_variant = "Q4_K_M" if "Q4_K_M" in variant_map else next(iter(variant_map))
        entry = ModelEntry(
            name=name,
            display_name=short.replace("-", " "),
            family=family,
            parameter_count_billions=params,
            description=f"Added from Hugging Face: {repo_id}",
            license="see model card",
            variants=variant_map,
            default_variant=default_variant,
            tags=["huggingface"],
        )
        self._manager.registry.add_model(entry)
        return {"id": entry.full_id, "name": entry.name, "variants": len(variant_map)}

    def list_models(self, dynamic: bool = True) -> list[dict[str, Any]]:
        """List all models in the registry annotated with local status and hardware fit.

        When `dynamic`, each model's quantization variants are fetched live from
        Hugging Face (cached), so the catalog shows every available quant with
        real sizes; falls back to the built-in list when offline.
        """
        registry_models = self._manager.registry.list_models()
        local_files = {f["filename"]: f for f in self._store.list_local_models()}
        probe_report = run_full_probe(self._settings.models_path)

        models_list: list[dict[str, Any]] = []

        for entry in registry_models:
            variants_info = []
            for quant, var in self._resolve_variants(entry, dynamic):
                is_downloaded = var.huggingface_file in local_files
                local_file_info = local_files.get(var.huggingface_file)

                # Assess hardware fit. Pass the REAL on-disk size so the weight
                # term is exact (and correct even for added models whose param
                # count can't be parsed from the repo name).
                fit = assess_model_fit(
                    report=probe_report,
                    model_name=entry.display_name,
                    parameter_count_billions=entry.parameter_count_billions,
                    quantization=quant,
                    target_context=self._settings.default_context_length,
                    actual_size_bytes=var.file_size_bytes,
                )

                variants_info.append(
                    {
                        "quantization": quant,
                        "file_size_bytes": var.file_size_bytes,
                        "is_downloaded": is_downloaded,
                        "local_path": local_file_info["path"] if is_downloaded else None,
                        "fit_level": fit.fit_level.value,
                        "fit_explanation": fit.explanation,
                        "recommendations": fit.recommendations,
                        "max_context": fit.max_context,
                    }
                )

            models_list.append(
                {
                    "id": entry.full_id,
                    "name": entry.name,
                    "display_name": entry.display_name,
                    "family": entry.family,
                    "parameter_count_billions": entry.parameter_count_billions,
                    "description": entry.description,
                    "license": entry.license,
                    "context_length": entry.context_length,
                    "tags": entry.tags,
                    "supports_vision": self._supports_vision(entry, variants_info),
                    "variants": variants_info,
                }
            )

        return models_list

    def _supports_vision(self, entry: Any, variants_info: list[dict[str, Any]]) -> bool:
        """Whether a model can take images.

        Definitive when downloaded: a companion mmproj GGUF sits next to the
        weights. Otherwise advisory, from the model's name/family/tags — so the
        UI can offer the image button for known vision families before download.
        """
        from pathlib import Path

        from localy.inference.engine import find_mmproj

        for v in variants_info:
            path = v.get("local_path")
            if path and find_mmproj(Path(path)) is not None:
                return True

        haystack = f"{entry.full_id} {entry.family} {' '.join(entry.tags)}".lower()
        markers = ("vl", "vision", "llava", "minicpm-v", "moondream", "-vl-", "vl-", "multimodal")
        return any(m in haystack for m in markers)

    async def get_active_model(self) -> LoadedModelInfo | None:
        """Get the active model info from the engine."""
        engine = get_engine(self._settings)
        return await engine.get_loaded_model_info()

    async def load_model(self, model_spec: str, context_length: int | None = None) -> LoadedModelInfo:
        """Load a model using the optimal config for this machine."""
        entry, variant = self._manager.registry.resolve(model_spec)
        model_path = self._manager.get_local_model_path(model_spec)

        logger.info("requesting_model_load", model_spec=model_spec)

        # Run probe and compute optimal config
        report = run_full_probe(self._settings.models_path)
        config = compute_inference_config(
            report=report,
            model_size_bytes=model_path.stat().st_size,
            requested_context=context_length,
            profile=self._settings.tuning_profile,
            thread_override=self._settings.thread_count_override,
            batch_override=self._settings.batch_size_override,
        )

        engine = get_engine(self._settings)
        await engine.load_model(
            model_id=entry.full_id,
            model_path=model_path,
            config=config,
        )

        info = await engine.get_loaded_model_info()
        if info is None:
            raise RuntimeError("Model reported loaded but engine returned no loaded model info.")
        return info

    async def unload_model(self) -> None:
        """Unload any loaded model."""
        engine = get_engine(self._settings)
        await engine.unload_model()

    async def pull_model(
        self,
        model_spec: str,
        progress_callback: Callable[[int, int, float], None] | None = None,
        force: bool = False,
    ) -> Path:
        """Download model weights."""
        return await self._manager.pull_model(model_spec, progress_callback, force)

    async def delete_model(self, model_spec: str) -> None:
        """Delete model weights from disk (unloading first if it's active)."""
        # If this model is currently loaded, unload it so the file isn't locked.
        engine = get_engine(self._settings)
        active = await engine.get_loaded_model_info()
        if active is not None:
            try:
                entry, _ = self._manager.registry.resolve(model_spec)
                if active.model_id == entry.full_id:
                    await engine.unload_model()
            except Exception:
                pass
        self._manager.delete_model(model_spec)
