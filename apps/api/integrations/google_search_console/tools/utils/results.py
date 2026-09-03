# apps/api/integrations/google_search_console/tools/utils/results.py

"""Bound Search Console sitemap submission results by audience."""

from collections.abc import Mapping, Sequence
from typing import Any


def sitemap_submission_results(
    outcomes: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Returns separate model and transcript projections for sitemap outcomes."""
    submitted_count = sum(item["outcome"] == "submitted" for item in outcomes)
    counts = {
        "submitted_count": submitted_count,
        "failed_count": sum(item["outcome"] == "failed" for item in outcomes),
    }
    model_rows = [
        {
            "sitemap_url": item["sitemap_url"],
            "outcome": item["outcome"],
            "previously_submitted": item["previously_submitted"],
            "status_read": item["status_read"],
            "error_code": item.get("error_code"),
        }
        for item in outcomes
    ]
    return {
        "model_result": {"sitemaps": model_rows, **counts},
        "display_result": {"sitemaps": [dict(item) for item in outcomes], **counts},
    }
