# apps/api/tests/integrations/google_search_console/test_write_evidence.py

"""Search Console sitemap mutation evidence coverage."""

import pytest
from pydantic import ValidationError

from integrations.google_search_console.tools.schemas.sitemap_submission import (
    GoogleSearchConsoleSitemapSubmissionResult,
)
from integrations.google_search_console.tools.utils.mutation_evidence import (
    audit_status,
    sitemap_pending_detail,
    sitemap_terminal_detail,
)
from services.audit_events import AuditStatus

from .support import site_entry


def test_sitemap_evidence_preserves_order_and_exact_counts() -> None:
    entry = site_entry(write_allowed=True)
    items = [
        {"sitemap_url": "https://example.com/one.xml", "previously_submitted": True},
        {"sitemap_url": "https://example.com/two.xml", "previously_submitted": False},
        {"sitemap_url": "https://example.com/three.xml", "previously_submitted": False},
    ]
    pending = sitemap_pending_detail(entry, items)
    terminal = sitemap_terminal_detail(
        pending,
        [
            {
                **items[0],
                "outcome": "submitted",
                "status_read": True,
                "last_submitted": "2026-09-03T11:10:00Z",
                "is_pending": True,
                "warnings": 0,
                "errors": 0,
                "error_code": None,
            },
            {
                **items[1],
                "outcome": "failed",
                "status_read": False,
                "last_submitted": None,
                "is_pending": None,
                "warnings": None,
                "errors": None,
                "error_code": "rejected",
            },
            {
                **items[2],
                "outcome": "unverified",
                "status_read": False,
                "last_submitted": None,
                "is_pending": None,
                "warnings": None,
                "errors": None,
                "error_code": "unverified",
            },
        ],
    )

    assert pending.intent_groups[0].items[0].fields == items[0]
    assert terminal.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 0,
        "failed": 1,
        "unverified": 1,
    }
    assert terminal.effect_counts == terminal.intent_counts
    assert terminal.outcome_groups[0].outcomes[0].effects[0].external_ref == items[0]["sitemap_url"]
    assert audit_status(terminal) is AuditStatus.UNVERIFIED


def test_sitemap_result_rejects_error_codes_outside_the_public_contract() -> None:
    with pytest.raises(ValidationError):
        GoogleSearchConsoleSitemapSubmissionResult.model_validate(
            {
                "sitemap_url": "https://example.com/sitemap.xml",
                "outcome": "failed",
                "previously_submitted": False,
                "status_read": False,
                "error_code": "IntegrationPermissionError",
            }
        )
