"""Knowledge-base settings tests."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_search_settings_defaults() -> None:
    resolved = Settings()

    assert resolved.KB_SOURCE_REFRESH_INTERVAL_SECONDS == 21_600
    assert resolved.KB_SOURCE_SCAN_BATCH_SIZE == 100
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


@pytest.mark.parametrize(
    ("setting_name", "value"),
    (
        ("KB_SOURCE_REFRESH_INTERVAL_SECONDS", 86_401),
        ("KB_SOURCE_SCAN_BATCH_SIZE", 1_001),
    ),
)
def test_source_reconciliation_settings_have_hard_limits(
    setting_name: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError, match=setting_name):
        Settings(**{setting_name: value})
