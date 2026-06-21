"""
Localy token counting utilities.

Provides exact token counting if a loaded llama.cpp model is available,
and heuristic approximations when no model is loaded.
"""

from __future__ import annotations

import re
from typing import Any

from localy.core.logging import get_logger

logger = get_logger(__name__)


def count_tokens(text: str, llm: Any | None = None) -> int:
    """Count the number of tokens in the given text.

    Args:
        text: Input string.
        llm: Optional llama_cpp.Llama instance. If provided, uses the model's
             actual tokenizer for 100% accurate count. If None, uses a heuristic.

    Returns:
        Number of tokens.
    """
    if not text:
        return 0

    if llm is not None:
        try:
            # llama-cpp-python expects bytes for tokenization
            encoded = text.encode("utf-8", errors="ignore")
            tokens = llm.tokenize(encoded, add_bos=False)
            return len(tokens)
        except Exception as e:
            logger.warning("model_tokenization_failed", error=str(e))
            # Fall back to heuristic

    # Heuristic: roughly 1 token ≈ 4 characters, or ~1.3 tokens per word.
    # We combine these: count words, count non-word characters, and take a weighted sum.
    words = re.findall(r"\w+", text)
    word_count = len(words)
    char_count = len(text)

    if word_count == 0:
        return max(1, char_count // 4)

    # Standard heuristic is ~0.75 words per token (1.33 tokens per word)
    estimated_tokens = int(word_count * 1.3)

    # Ensure it's at least proportional to characters (minimum 1 token per 4 chars for code/symbols)
    min_tokens = max(1, char_count // 4)

    return max(estimated_tokens, min_tokens)
