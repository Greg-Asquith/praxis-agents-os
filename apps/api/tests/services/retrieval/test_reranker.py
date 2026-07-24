"""Reranker seam tests."""

from services.retrieval import get_reranker


def test_default_reranker_is_disabled() -> None:
    assert get_reranker() is None
