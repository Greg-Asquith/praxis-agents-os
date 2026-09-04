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


def indexing_notification_results(
    outcomes: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Returns separate model and transcript projections for indexing outcomes."""
    counts = {
        "notified_count": sum(item["outcome"] == "notified" for item in outcomes),
        "failed_count": sum(item["outcome"] == "failed" for item in outcomes),
    }
    model_rows = [
        {
            "url": item["url"],
            "notification_type": item["notification_type"],
            "page_type": item["page_type"],
            "outcome": item["outcome"],
            "notify_time": item.get("notify_time"),
            "error_code": item.get("error_code"),
        }
        for item in outcomes
    ]
    return {
        "model_result": {"notifications": model_rows, **counts},
        "display_result": {"notifications": [dict(item) for item in outcomes], **counts},
    }
