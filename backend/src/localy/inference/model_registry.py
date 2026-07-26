"""
Curated model registry — Ollama-style model catalog.

Maps friendly names (e.g., "llama3:8b-q4_k_m") to HuggingFace GGUF files.
Includes metadata: parameter count, quantization, file size, SHA256, and
recommended draft models for speculative decoding.

Registry is a JSON manifest that ships with the app and can be updated
from a remote URL without a full app update.

Usage:
    registry = ModelRegistry(registry_dir)
    model = registry.resolve("llama3:8b")  # Returns ModelEntry
    model = registry.resolve("llama3:8b-q4_k_m")  # Specific quant
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from localy.core.constants import REGISTRY_FILENAME
from localy.core.exceptions import ModelNotFoundError
from localy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class QuantVariant:
    """A specific quantization variant of a model.

    Attributes:
        quantization: Quantization type (e.g., Q4_K_M).
        file_size_bytes: File size in bytes.
        huggingface_repo: HuggingFace repo ID.
        huggingface_file: GGUF filename within the repo.
        sha256: SHA256 hash for verification.
        download_url: Direct download URL (computed or explicit).
    """

    quantization: str
    file_size_bytes: int
    huggingface_repo: str
    huggingface_file: str
    sha256: str = ""
    download_url: str = ""

    @property
    def file_size_gb(self) -> float:
        """File size in GB."""
        return self.file_size_bytes / (1024**3)

    @property
    def resolved_download_url(self) -> str:
        """Get the download URL (direct or computed from HuggingFace)."""
        if self.download_url:
            return self.download_url
        return (
            f"https://huggingface.co/{self.huggingface_repo}/resolve/main/{self.huggingface_file}"
        )


@dataclass
class ModelEntry:
    """A model in the registry.

    Attributes:
        name: Short model name (e.g., "llama3").
        display_name: Human-readable display name.
        family: Model family (e.g., "llama", "mistral", "phi").
        parameter_count_billions: Parameter count in billions.
        description: Brief model description.
        license: Model license (e.g., "MIT", "Llama 3 Community").
        context_length: Default/max context length.
        variants: Available quantization variants.
        default_variant: Default quantization (usually Q4_K_M).
        draft_model: Name of recommended draft model for speculative decoding.
        supports_mtp: Whether the model supports Multi-Token Prediction.
        tags: Searchable tags (e.g., ["chat", "code", "instruct"]).
    """

    name: str
    display_name: str
    family: str
    parameter_count_billions: float
    description: str = ""
    license: str = ""
    context_length: int = 4096
    variants: dict[str, QuantVariant] = field(default_factory=dict)
    default_variant: str = "Q4_K_M"
    draft_model: str = ""
    supports_mtp: bool = False
    tags: list[str] = field(default_factory=list)

    def get_variant(self, quantization: str | None = None) -> QuantVariant:
        """Get a specific quantization variant.

        Args:
            quantization: Quantization type. None for default.

        Returns:
            The requested QuantVariant.

        Raises:
            ModelNotFoundError: If the variant doesn't exist.
        """
        quant = quantization or self.default_variant
        variant = self.variants.get(quant)
        if variant is None:
            available = ", ".join(sorted(self.variants.keys()))
            raise ModelNotFoundError(
                f"Quantization '{quant}' not available for {self.name}. Available: {available}",
                details={"model": self.name, "requested_quant": quant, "available": list(self.variants.keys())},
            )
        return variant

    @property
    def full_id(self) -> str:
        """Full model identifier (e.g., 'llama3:8b')."""
        param_str = f"{self.parameter_count_billions:.0f}b" if self.parameter_count_billions >= 1 else f"{self.parameter_count_billions * 1000:.0f}m"
        return f"{self.name}:{param_str}"


class ModelRegistry:
    """Curated model catalog with Ollama-style name resolution.

    Supports:
    - "llama3:8b" → resolves to default quant (Q4_K_M)
    - "llama3:8b-q4_k_m" → resolves to specific quant
    - "llama3" → resolves to largest matching model + default quant
    """

    def __init__(self, registry_dir: Path) -> None:
        self._registry_dir = registry_dir
        self._models: dict[str, ModelEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from disk or initialize with built-in defaults."""
        registry_file = self._registry_dir / REGISTRY_FILENAME
        if registry_file.exists():
            try:
                data = json.loads(registry_file.read_text(encoding="utf-8"))
                self._parse_registry(data)
                logger.info("registry_loaded", model_count=len(self._models), source="file")
                return
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("registry_file_invalid", error=str(e))

        # Initialize with built-in defaults
        self._init_builtin_registry()
        self._save()
        logger.info("registry_initialized", model_count=len(self._models), source="builtin")

    def _parse_registry(self, data: dict[str, Any]) -> None:
        """Parse registry JSON data into ModelEntry objects."""
        for model_data in data.get("models", []):
            variants = {}
            for v_data in model_data.get("variants", []):
                quant = v_data["quantization"]
                variants[quant] = QuantVariant(
                    quantization=quant,
                    file_size_bytes=v_data.get("file_size_bytes", 0),
                    huggingface_repo=v_data.get("huggingface_repo", ""),
                    huggingface_file=v_data.get("huggingface_file", ""),
                    sha256=v_data.get("sha256", ""),
                    download_url=v_data.get("download_url", ""),
                )

            entry = ModelEntry(
                name=model_data["name"],
                display_name=model_data.get("display_name", model_data["name"]),
                family=model_data.get("family", ""),
                parameter_count_billions=model_data["parameter_count_billions"],
                description=model_data.get("description", ""),
                license=model_data.get("license", ""),
                context_length=model_data.get("context_length", 4096),
                variants=variants,
                default_variant=model_data.get("default_variant", "Q4_K_M"),
                draft_model=model_data.get("draft_model", ""),
                supports_mtp=model_data.get("supports_mtp", False),
                tags=model_data.get("tags", []),
            )
            self._models[entry.full_id] = entry

    def _init_builtin_registry(self) -> None:
        """Initialize with a curated set of known-good models."""
        builtin_models = [
            ModelEntry(
                name="llama3.2",
                display_name="Llama 3.2 3B Instruct",
                family="llama",
                parameter_count_billions=3.0,
                description="Meta's compact instruction-following model. Fast and efficient.",
                license="Llama 3.2 Community License",
                context_length=131072,
                default_variant="Q4_K_M",
                tags=["chat", "instruct", "compact"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(2.0 * 1024**3),
                        huggingface_repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
                        huggingface_file="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
                    ),
                    "Q8_0": QuantVariant(
                        quantization="Q8_0",
                        file_size_bytes=int(3.4 * 1024**3),
                        huggingface_repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
                        huggingface_file="Llama-3.2-3B-Instruct-Q8_0.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="llama3.1",
                display_name="Llama 3.1 8B Instruct",
                family="llama",
                parameter_count_billions=8.0,
                description="Meta's flagship 8B instruction-following model. Excellent all-rounder.",
                license="Llama 3.1 Community License",
                context_length=131072,
                default_variant="Q4_K_M",
                draft_model="llama3.2:3b-q4_k_m",
                tags=["chat", "instruct", "versatile"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(4.9 * 1024**3),
                        huggingface_repo="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
                        huggingface_file="Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
                    ),
                    "Q5_K_M": QuantVariant(
                        quantization="Q5_K_M",
                        file_size_bytes=int(5.7 * 1024**3),
                        huggingface_repo="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
                        huggingface_file="Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf",
                    ),
                    "Q8_0": QuantVariant(
                        quantization="Q8_0",
                        file_size_bytes=int(8.5 * 1024**3),
                        huggingface_repo="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
                        huggingface_file="Meta-Llama-3.1-8B-Instruct-Q8_0.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="qwen2.5",
                display_name="Qwen 2.5 7B Instruct",
                family="qwen",
                parameter_count_billions=7.0,
                description="Alibaba's strong 7B model. Excellent at reasoning and code.",
                license="Apache 2.0",
                context_length=131072,
                default_variant="Q4_K_M",
                tags=["chat", "instruct", "code", "reasoning"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(4.7 * 1024**3),
                        huggingface_repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
                        huggingface_file="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                    ),
                    "Q8_0": QuantVariant(
                        quantization="Q8_0",
                        file_size_bytes=int(8.1 * 1024**3),
                        huggingface_repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
                        huggingface_file="Qwen2.5-7B-Instruct-Q8_0.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="phi-4",
                display_name="Phi-4 14B",
                family="phi",
                parameter_count_billions=14.0,
                description="Microsoft's efficient 14B model. Strong reasoning at smaller size.",
                license="MIT",
                context_length=16384,
                default_variant="Q4_K_M",
                tags=["chat", "reasoning", "code"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(8.4 * 1024**3),
                        huggingface_repo="bartowski/phi-4-GGUF",
                        huggingface_file="phi-4-Q4_K_M.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="gemma2",
                display_name="Gemma 2 9B Instruct",
                family="gemma",
                parameter_count_billions=9.0,
                description="Google's efficient 9B instruction model.",
                license="Gemma Terms of Use",
                context_length=8192,
                default_variant="Q4_K_M",
                tags=["chat", "instruct"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(5.5 * 1024**3),
                        huggingface_repo="bartowski/gemma-2-9b-it-GGUF",
                        huggingface_file="gemma-2-9b-it-Q4_K_M.gguf",
                    ),
                    "Q8_0": QuantVariant(
                        quantization="Q8_0",
                        file_size_bytes=int(9.8 * 1024**3),
                        huggingface_repo="bartowski/gemma-2-9b-it-GGUF",
                        huggingface_file="gemma-2-9b-it-Q8_0.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="mistral",
                display_name="Mistral 7B Instruct v0.3",
                family="mistral",
                parameter_count_billions=7.0,
                description="Mistral AI's versatile 7B instruction model.",
                license="Apache 2.0",
                context_length=32768,
                default_variant="Q4_K_M",
                tags=["chat", "instruct", "versatile"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(4.4 * 1024**3),
                        huggingface_repo="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
                        huggingface_file="Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
                    ),
                    "Q8_0": QuantVariant(
                        quantization="Q8_0",
                        file_size_bytes=int(7.7 * 1024**3),
                        huggingface_repo="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
                        huggingface_file="Mistral-7B-Instruct-v0.3-Q8_0.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="deepseek-r1",
                display_name="DeepSeek R1 Distill Qwen 7B",
                family="deepseek",
                parameter_count_billions=7.0,
                description="DeepSeek's reasoning-focused 7B distilled model.",
                license="MIT",
                context_length=131072,
                default_variant="Q4_K_M",
                tags=["chat", "reasoning", "code"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(4.7 * 1024**3),
                        huggingface_repo="bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
                        huggingface_file="DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
                    ),
                },
            ),
            ModelEntry(
                name="smollm2",
                display_name="SmolLM2 1.7B Instruct",
                family="smollm",
                parameter_count_billions=1.7,
                description="Hugging Face's tiny model. Ultra-fast, great for testing and draft.",
                license="Apache 2.0",
                context_length=8192,
                default_variant="Q4_K_M",
                tags=["compact", "fast", "draft"],
                variants={
                    "Q4_K_M": QuantVariant(
                        quantization="Q4_K_M",
                        file_size_bytes=int(1.1 * 1024**3),
                        huggingface_repo="bartowski/SmolLM2-1.7B-Instruct-GGUF",
                        huggingface_file="SmolLM2-1.7B-Instruct-Q4_K_M.gguf",
                    ),
                    "Q8_0": QuantVariant(
                        quantization="Q8_0",
                        file_size_bytes=int(1.8 * 1024**3),
                        huggingface_repo="bartowski/SmolLM2-1.7B-Instruct-GGUF",
                        huggingface_file="SmolLM2-1.7B-Instruct-Q8_0.gguf",
                    ),
                },
            ),
        ]

        for model in builtin_models:
            self._models[model.full_id] = model

    def add_model(self, model: ModelEntry) -> None:
        """Add (or replace) a model in the registry and persist it."""
        self._models[model.full_id] = model
        self._save()

    def _save(self) -> None:
        """Save registry to disk."""
        data: dict[str, Any] = {"version": 1, "models": []}
        for model in self._models.values():
            model_data: dict[str, Any] = {
                "name": model.name,
                "display_name": model.display_name,
                "family": model.family,
                "parameter_count_billions": model.parameter_count_billions,
                "description": model.description,
                "license": model.license,
                "context_length": model.context_length,
                "default_variant": model.default_variant,
                "draft_model": model.draft_model,
                "supports_mtp": model.supports_mtp,
                "tags": model.tags,
                "variants": [
                    {
                        "quantization": v.quantization,
                        "file_size_bytes": v.file_size_bytes,
                        "huggingface_repo": v.huggingface_repo,
                        "huggingface_file": v.huggingface_file,
                        "sha256": v.sha256,
                        "download_url": v.download_url,
                    }
                    for v in model.variants.values()
                ],
            }
            data["models"].append(model_data)

        self._registry_dir.mkdir(parents=True, exist_ok=True)
        registry_file = self._registry_dir / REGISTRY_FILENAME
        registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def resolve(self, model_spec: str) -> tuple[ModelEntry, QuantVariant]:
        """Resolve an Ollama-style model specification.

        Supports formats:
        - "llama3.1:8b" → model + default quant
        - "llama3.1:8b-q4_k_m" → model + specific quant
        - "llama3.1" → find best matching model + default quant

        Args:
            model_spec: Model specification string.

        Returns:
            Tuple of (ModelEntry, QuantVariant).

        Raises:
            ModelNotFoundError: If model or variant not found.
        """
        spec = model_spec.strip().lower()
        def _split_registered_quant(candidate: str, entry: ModelEntry) -> tuple[str, str | None]:
            # Dynamic Hugging Face models can expose quants outside our built-in
            # enum (for example IQ3_M). Split against the entry's actual variants
            # so every catalog variant can be addressed from chat/API.
            for quant in sorted(entry.variants.keys(), key=len, reverse=True):
                suffix = f"-{quant.lower()}"
                if candidate.endswith(suffix):
                    return candidate[: -len(suffix)], quant
            return candidate, None

        # Try exact match first
        for model_id, entry in self._models.items():
            base_spec, quant_override = _split_registered_quant(spec, entry)
            if model_id.lower() == base_spec or entry.name.lower() == base_spec:
                variant = entry.get_variant(quant_override)
                return entry, variant

        # Try partial match (name without size)
        matches = [
            entry for entry in self._models.values()
            if entry.name.lower() == _split_registered_quant(spec, entry)[0].split(":")[0]
        ]

        if matches:
            # Return the best match (prefer specified size, else first)
            if ":" in spec:
                size_spec = spec.split(":")[1].split("-", 1)[0]
                for m in matches:
                    _base_spec, quant_override = _split_registered_quant(spec, m)
                    if size_spec in m.full_id.lower():
                        return m, m.get_variant(quant_override)

            entry = matches[0]
            _base_spec, quant_override = _split_registered_quant(spec, entry)
            return entry, entry.get_variant(quant_override)

        # Not found
        available = ", ".join(sorted(self._models.keys()))
        raise ModelNotFoundError(
            f"Model '{model_spec}' not found in registry. Available: {available}",
            details={"requested": model_spec, "available": list(self._models.keys())},
        )

    def list_models(self) -> list[ModelEntry]:
        """List all models in the registry."""
        return list(self._models.values())

    def search(self, query: str) -> list[ModelEntry]:
        """Search models by name, family, or tags."""
        query = query.lower()
        return [
            model for model in self._models.values()
            if query in model.name.lower()
            or query in model.family.lower()
            or query in model.display_name.lower()
            or any(query in tag for tag in model.tags)
        ]
