"""Exact Google Ads mutation-ledger invariants and projections."""

import pytest

from integrations.google_ads.operations.mutation_outcomes import (
    CAMPAIGN_KEYWORD_MUTATION_SPEC,
    GoogleAdsMutationProjection,
    build_keyword_mutation_ledger,
    build_mutation_ledger,
)


def test_ledger_separates_parent_intents_from_any_expansion_effects() -> None:
    ledger = build_mutation_ledger(
        family="shared_set_keywords",
        action="remove",
        parent_fields=[
            {"text": "brand", "match_type": "ANY"},
            {"text": "missing", "match_type": "PHRASE"},
        ],
        skipped_indices={1: "not_found"},
        submitted=[
            (0, {"text": "Brand", "match_type": "EXACT"}),
            (0, {"text": "brand", "match_type": "BROAD"}),
        ],
        outcomes=[
            ("applied", "customers/1/sharedCriteria/2~10", None, None),
            ("failed", None, "CANNOT_REMOVE", "Criterion cannot be removed"),
        ],
        projection=GoogleAdsMutationProjection(
            applied_key="removed",
            skipped_key="not_found",
            errors_key="keyword_errors",
            error_scope="keyword",
        ),
    )

    assert ledger.intent_counts == {"requested": 2, "submitted": 1, "skipped": 1}
    assert ledger.effect_counts == {"applied": 1, "failed": 1, "unverified": 0}
    assert [effect.slot for effect in ledger.parents[0].effects] == [0, 1]
    assert ledger.result() == {
        "removed": [
            {
                "text": "Brand",
                "match_type": "EXACT",
                "resource_name": "customers/1/sharedCriteria/2~10",
            }
        ],
        "not_found": [{"text": "missing", "match_type": "PHRASE"}],
        "keyword_errors": [
            {
                "scope": "keyword",
                "text": "brand",
                "match_type": "BROAD",
                "message": "Criterion cannot be removed",
                "error_code": "CANNOT_REMOVE",
            }
        ],
        "resource_names": ["customers/1/sharedCriteria/2~10"],
    }


@pytest.mark.parametrize(
    ("submitted", "outcomes", "match"),
    [
        ((), (), "Submitted Google Ads parents require effects"),
        (
            ((0, {"campaign_id": "10"}), (0, {"campaign_id": "10"})),
            (
                ("applied", "customers/1/campaigns/10", None, None),
                ("applied", "customers/1/campaigns/10", None, None),
            ),
            "unique concrete identities",
        ),
        (
            ((1, {"campaign_id": "20"}),),
            (("failed", None, "FAILED", "Rejected"),),
            "unknown parent",
        ),
    ],
)
def test_ledger_rejects_missing_duplicate_and_out_of_range_accounting(
    submitted: tuple[tuple[int, dict[str, str]], ...],
    outcomes: tuple[tuple[str, str | None, str | None, str | None], ...],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        build_mutation_ledger(
            family="campaign_status",
            action="update",
            parent_fields=[{"campaign_id": "10"}],
            skipped_indices={},
            submitted=submitted,
            outcomes=outcomes,  # type: ignore[arg-type] -- invalid cases probe runtime validation.
            projection=GoogleAdsMutationProjection(
                applied_key="updated",
                skipped_key="skipped",
                errors_key="campaign_errors",
            ),
        )


def test_ledger_rejects_out_of_range_skipped_parent() -> None:
    with pytest.raises(ValueError, match="skipped outcome references an unknown parent"):
        build_mutation_ledger(
            family="campaign_status",
            action="update",
            parent_fields=[{"campaign_id": "10"}],
            skipped_indices={1: "already_applied"},
            submitted=[(0, {"campaign_id": "10"})],
            outcomes=[("applied", "customers/1/campaigns/10", None, None)],
            projection=GoogleAdsMutationProjection(
                applied_key="updated",
                skipped_key="skipped",
                errors_key="campaign_errors",
            ),
        )


@pytest.mark.parametrize(
    "effect_fields",
    [
        {"campaign_id": "20", "text": "brand", "match_type": "EXACT"},
        {"campaign_id": "10", "text": "other", "match_type": "EXACT"},
        {"campaign_id": "10", "text": "brand", "match_type": "BROAD"},
    ],
)
def test_keyword_ledger_rejects_effects_attributed_to_a_different_parent(
    effect_fields: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="does not match its parent intent"):
        build_keyword_mutation_ledger(
            spec=CAMPAIGN_KEYWORD_MUTATION_SPEC,
            action="add",
            parent_fields=[{"campaign_id": "10", "text": "Brand", "match_type": "EXACT"}],
            skipped_indices={},
            submitted=[(0, effect_fields)],
            outcomes=[("applied", "customers/1/campaignCriteria/10~1", None, None)],
        )


def test_keyword_ledger_accepts_casefolded_text_and_any_expansion() -> None:
    ledger = build_keyword_mutation_ledger(
        spec=CAMPAIGN_KEYWORD_MUTATION_SPEC,
        action="remove",
        parent_fields=[{"campaign_id": "10", "text": "Brand", "match_type": "ANY"}],
        skipped_indices={},
        submitted=[
            (0, {"campaign_id": "10", "text": "brand", "match_type": "EXACT"}),
            (0, {"campaign_id": "10", "text": "BRAND", "match_type": "BROAD"}),
        ],
        outcomes=[
            ("applied", "customers/1/campaignCriteria/10~1", None, None),
            ("applied", "customers/1/campaignCriteria/10~2", None, None),
        ],
    )

    assert [
        row["match_type"] for row in ledger.keyword_outcomes(entity_id_key="campaign_id")["10"]
    ] == [
        "EXACT",
        "BROAD",
    ]


def test_unverified_effect_fails_closed_after_provider_dispatch() -> None:
    ledger = build_mutation_ledger(
        family="campaign_status",
        action="update",
        parent_fields=[{"campaign_id": "10"}],
        skipped_indices={},
        submitted=[(0, {"campaign_id": "10"})],
        outcomes=[
            (
                "unverified",
                None,
                "UNACCOUNTED_OPERATION",
                "Google Ads did not account for this submitted operation",
            )
        ],
        projection=GoogleAdsMutationProjection(
            applied_key="updated",
            skipped_key="skipped",
            errors_key="campaign_errors",
        ),
    )

    with pytest.raises(ValueError, match="could not be verified exactly"):
        ledger.require_verified()
