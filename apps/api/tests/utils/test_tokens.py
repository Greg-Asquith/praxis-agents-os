# apps/api/tests/utils/test_tokens.py

"""Tests for deterministic runtime token estimates."""

import pytest

from utils.tokens import estimate_tokens


def test_estimate_tokens_counts_ascii_with_configured_divisor() -> None:
    assert estimate_tokens("a" * 9) == 3
    assert estimate_tokens("a" * 9, chars_per_token=3.0) == 3


def test_estimate_tokens_counts_non_ascii_conservatively() -> None:
    assert estimate_tokens("漢字かな") >= 4
    assert estimate_tokens("abc漢字", chars_per_token=4.0) == 3


def test_estimate_tokens_handles_empty_text_and_rejects_invalid_divisor() -> None:
    assert estimate_tokens("") == 0
    with pytest.raises(ValueError, match="greater than zero"):
        estimate_tokens("text", chars_per_token=0)
