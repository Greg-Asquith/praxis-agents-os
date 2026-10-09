# apps/api/integrations/meta_ads/operations/ad_review.py

"""Read Meta's review outcome and delivery issues for ads as short, bounded text."""

from collections.abc import Mapping
from typing import Any

from ..tools.schemas.objects import MetaAdsReviewState

_MAX_ITEMS = 5
_MAX_TEXT = 300
_REVIEW_STATES: dict[str, MetaAdsReviewState] = {
    "PENDING_REVIEW": "in_review",
    "IN_PROCESS": "in_review",
    "DISAPPROVED": "rejected",
    "WITH_ISSUES": "with_issues",
    "ACTIVE": "approved",
    "PREAPPROVED": "approved",
}


def review_state(effective_status: str | None) -> MetaAdsReviewState:
    """Maps delivery status to review; an ad that is off doesn't show whether it passed."""
    return _REVIEW_STATES.get(effective_status or "", "unknown")


def review_reasons(raw: Mapping[str, Any]) -> list[str]:
    """Returns up to five rejection reasons from `ad_review_feedback`, as policy: reason."""
    feedback = raw.get("ad_review_feedback")
    if not isinstance(feedback, Mapping):
        return []
    reasons: list[str] = []
    for scope in ("global", "placement_specific"):
        entries = feedback.get(scope)
        if not isinstance(entries, Mapping):
            continue
        for policy, reason in entries.items():
            text = _text(reason if isinstance(reason, str) else _first_text(reason))
            label = _text(str(policy).replace("_", " ").capitalize())
            if text or label:
                reasons.append(f"{label}: {text}"[:_MAX_TEXT] if text else label)
    return reasons[:_MAX_ITEMS]


def issue_summaries(raw: Mapping[str, Any]) -> list[str]:
    """Returns up to five delivery issue summaries from `issues_info`."""
    issues = raw.get("issues_info")
    if not isinstance(issues, list):
        return []
    summaries = [
        _text(issue.get("error_summary") or issue.get("error_message"))
        for issue in issues
        if isinstance(issue, Mapping)
    ]
    return [summary for summary in summaries if summary][:_MAX_ITEMS]


def _first_text(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return next((item for item in value.values() if isinstance(item, str)), None)
    return None


def _text(value: Any) -> str:
    return " ".join(value.split())[:_MAX_TEXT] if isinstance(value, str) else ""
