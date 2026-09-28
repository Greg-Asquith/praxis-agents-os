"""Knowledge-base settings tests."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_search_candidate_limit_must_cover_the_accepted_top_k() -> None:
    with pytest.raises(ValidationError, match="KB_SEARCH_CTE_LIMIT"):
        Settings(KB_SEARCH_TOP_K_MAX=50, KB_SEARCH_CTE_LIMIT=49)

    resolved = Settings(KB_SEARCH_TOP_K_MAX=50, KB_SEARCH_CTE_LIMIT=50)
    assert resolved.KB_SEARCH_CTE_LIMIT == resolved.KB_SEARCH_TOP_K_MAX
