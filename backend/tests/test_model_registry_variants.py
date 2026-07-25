from __future__ import annotations

import sys

sys.path.insert(0, "src")

from localy.inference.model_registry import ModelEntry, ModelRegistry, QuantVariant


def test_resolve_supports_dynamic_non_enum_quant_suffix(tmp_path) -> None:
    registry = ModelRegistry(tmp_path)
    registry.add_model(
        ModelEntry(
            name="custom-model",
            display_name="Custom Model",
            family="custom",
            parameter_count_billions=7,
            default_variant="Q4_K_M",
            variants={
                "Q4_K_M": QuantVariant(
                    quantization="Q4_K_M",
                    file_size_bytes=10,
                    huggingface_repo="owner/repo",
                    huggingface_file="custom-Q4_K_M.gguf",
                ),
                "IQ3_M": QuantVariant(
                    quantization="IQ3_M",
                    file_size_bytes=5,
                    huggingface_repo="owner/repo",
                    huggingface_file="custom-IQ3_M.gguf",
                ),
            },
        )
    )

    entry, variant = registry.resolve("custom-model:7b-iq3_m")

    assert entry.name == "custom-model"
    assert variant.quantization == "IQ3_M"
