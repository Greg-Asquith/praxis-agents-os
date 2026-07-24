"""Knowledge-base search settings tests."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_search_settings_defaults() -> None:
    resolved = Settings()

    assert resolved.KB_SEARCH_TOP_K_DEFAULT == 10
    assert resolved.KB_SEARCH_TOP_K_MAX == 50
    assert resolved.KB_SEARCH_CTE_LIMIT == 50
    assert resolved.KB_SEARCH_EF_SEARCH == 100
    assert resolved.KB_RERANKER == "none"
    assert resolved.KB_SEARCH_RECENCY_WEIGHT == 0.25
    assert resolved.KB_SEARCH_RECENCY_SOURCE_TYPES == (
        "url",
        "conversation",
        "integration",
    )


def test_search_candidate_limit_must_cover_the_accepted_top_k() -> None:
    with pytest.raises(ValidationError, match="KB_SEARCH_CTE_LIMIT"):
        Settings(KB_SEARCH_TOP_K_MAX=50, KB_SEARCH_CTE_LIMIT=49)

    resolved = Settings(KB_SEARCH_TOP_K_MAX=50, KB_SEARCH_CTE_LIMIT=50)
    assert resolved.KB_SEARCH_CTE_LIMIT == resolved.KB_SEARCH_TOP_K_MAX
