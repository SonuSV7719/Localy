"""
Localy Speculative Decoding Orchestration.

Implements pairing a main model with a smaller "draft" model or
using prompt lookup decoding (ngram matching) for acceleration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from localy.core.config import Settings
from localy.core.logging import get_logger

logger = get_logger(__name__)


def setup_speculative_decoding(
    settings: Settings,
    main_model_id: str,
    draft_model_path: Path | None = None,
    num_pred_tokens: int = 4,
) -> Any | None:
    """Setup speculative decoding for a model.

    If a draft model GGUF path is provided, loads the draft model.
    Otherwise, falls back to Prompt Lookup Decoding (ngram-based lookup),
    which provides a speedup without extra memory overhead.

    Args:
        settings: Application settings.
        main_model_id: ID of the main model.
        draft_model_path: Optional path to a draft model GGUF file.
        num_pred_tokens: Number of look-ahead tokens to predict (default 4 on CPU).

    Returns:
        The draft_model object to pass to the main Llama constructor, or None.
    """
    # If a real draft model GGUF path is specified and exists, load it
    if draft_model_path and draft_model_path.exists():
        try:
            from llama_cpp import Llama

            logger.info("loading_draft_model", path=str(draft_model_path))
            # Load draft model with minimal threads and context to reduce overhead
            draft_model = Llama(
                model_path=str(draft_model_path),
                n_ctx=2048,  # Small context is sufficient for drafting
                n_threads=max(1, settings.thread_count_override or 2),
                n_gpu_layers=0,  # Run draft model on CPU
                verbose=False,
            )
            logger.info("draft_model_loaded_successfully", main_id=main_model_id)
            return draft_model
        except Exception as e:
            logger.warning("failed_to_load_draft_model", error=str(e))
            # Fall back to prompt lookup decoding rather than failing

    # Prompt Lookup Decoding (ngram-based matching)
    try:
        from llama_cpp.llama_speculative import LlamaPromptLookupDecoding

        logger.info(
            "enabling_prompt_lookup_decoding",
            num_pred_tokens=num_pred_tokens,
            main_id=main_model_id,
        )
        return LlamaPromptLookupDecoding(num_pred_tokens=num_pred_tokens)
    except (ImportError, AttributeError) as e:
        logger.warning("prompt_lookup_decoding_not_supported", error=str(e))

    return None
