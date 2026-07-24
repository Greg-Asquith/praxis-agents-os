"""Weighted reciprocal-rank fusion tests."""

from uuid import UUID

import pytest

from services.retrieval import RankedId, rrf_merge

_A = UUID(int=1)
_B = UUID(int=2)
_C = UUID(int=3)


def test_rrf_merge_fuses_lists_and_uses_deterministic_ties() -> None:
    results = rrf_merge(
        {
            "lexical": [RankedId(_A, 1), RankedId(_B, 2)],
            "semantic": [RankedId(_A, 2), RankedId(_C, 1)],
        },
        limit=3,
    )

    assert [result.id for result in results] == [_A, _C, _B]
    assert results[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert results[0].sources == frozenset({"lexical", "semantic"})

    tied = rrf_merge(
        {"lexical": [RankedId(_C, 1)], "semantic": [RankedId(_B, 1)]},
        limit=2,
    )
    assert [result.id for result in tied] == [_B, _C]
    assert tied[0].score == tied[1].score


def test_rrf_merge_weights_lists_without_changing_source_provenance() -> None:
    lists = {
        "lexical": [RankedId(_A, 1)],
        "recency": [RankedId(_B, 1)],
    }

    unweighted = rrf_merge(lists, limit=2)
    equal_weighted = rrf_merge(
        lists,
        limit=2,
        weights={"lexical": 1.0, "recency": 1.0},
    )
    recency_disabled = rrf_merge(
        lists,
        limit=2,
        weights={"lexical": 1.0, "recency": 0.0},
    )

    assert equal_weighted == unweighted
    assert [result.id for result in recency_disabled] == [_A, _B]
    assert recency_disabled[1].score == 0
    assert recency_disabled[1].sources == frozenset({"recency"})


def test_rrf_merge_handles_empty_and_one_sided_inputs() -> None:
    assert rrf_merge({}, limit=10) == []
    assert rrf_merge({"lexical": []}, limit=10) == []
    result = rrf_merge({"lexical": [RankedId(_A, 1)]}, limit=1)
    assert result[0].id == _A


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"k": -1, "limit": 1}, "k"),
        ({"limit": -1}, "limit"),
    ],
)
def test_rrf_merge_rejects_invalid_bounds(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        rrf_merge({}, **kwargs)


def test_rrf_merge_rejects_zero_based_ranks_and_negative_weights() -> None:
    with pytest.raises(ValueError, match="one-based"):
        rrf_merge({"lexical": [RankedId(_A, 0)]}, limit=1)
    with pytest.raises(ValueError, match="weights"):
        rrf_merge(
            {"lexical": [RankedId(_A, 1)]},
            limit=1,
            weights={"lexical": -1},
        )
