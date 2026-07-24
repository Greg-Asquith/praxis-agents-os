# apps/api/utils/tokens.py

"""Deterministic token-count estimates for runtime budgeting."""

import math


def estimate_tokens_by_character_count(
    text: str,
    *,
    chars_per_token: float = 4.0,
) -> int:
    """Estimate tokens using only a fixed character-count divisor."""
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be greater than zero")
    return math.floor(len(text) / chars_per_token)


def estimate_tokens(text: str, *, chars_per_token: float = 4.0) -> int:
    """Estimate tokens conservatively without a provider tokenizer.

    ASCII text uses the model catalog's calibrated characters-per-token
    divisor. Non-ASCII characters each count as one token so CJK and other
    dense scripts are not underestimated by the prose-oriented divisor.
    """
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be greater than zero")
    if not text:
        return 0

    ascii_chars = sum(character.isascii() for character in text)
    non_ascii_chars = len(text) - ascii_chars
    return math.ceil(ascii_chars / chars_per_token) + non_ascii_chars
