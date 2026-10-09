# apps/api/integrations/meta_ads/operations/ad_rows.py

"""Projects what one ad's creation proved into its ledger effect and result row."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..creative_features import applied_changes, change_labels
from .ad_review import review_reasons, review_state
from .create_objects import MetaCreateResult
from .mutations import (
    NOT_DISPATCHED_CODE,
    NOT_DISPATCHED_MESSAGE,
    MetaAdsMutationEffect,
    freeze_fields,
)
from .plan_ads import PlannedAd

_PREVIEW_HOSTS = frozenset({"facebook.com", "www.facebook.com", "fb.me"})
_READBACK_FAILED = "Meta Ads created this ad, but it couldn't be read back."
_UNEXPECTED_CHANGES = (
    "Meta turned on automatic changes to this ad: {labels}. Check it in Ads Manager."
)


@dataclass
class AdRun:
    """What one planned ad proved."""

    ad: PlannedAd
    fields: dict[str, str]
    outcome: MetaCreateResult | None = None
    # Set once the create has been handed to Meta, so an interruption is unverified.
    sending: bool = False
    skip_code: str | None = None
    skip_message: str | None = None
    read: dict[str, Any] | None = None

    @property
    def created_id(self) -> str | None:
        return self.outcome.object_id if self.outcome and self.outcome.status == "applied" else None


def _effect(
    fields: Mapping[str, str], outcome: str, error_code: str, message: str
) -> MetaAdsMutationEffect:
    return MetaAdsMutationEffect(
        fields=freeze_fields(fields), outcome=outcome, error_code=error_code, message=message
    )


def ad_effect(run: AdRun) -> MetaAdsMutationEffect:
    """Projects one ad's outcome into the ledger; created ads carry what Meta shows."""
    fields = dict(run.fields)
    if run.skip_code is not None:
        message = (run.skip_message or NOT_DISPATCHED_MESSAGE)[:1000]
        return _effect(fields, "failed", run.skip_code, message)
    outcome = run.outcome
    if outcome is None:
        return _interrupted_effect(run, fields)
    if outcome.status != "applied" or outcome.object_id is None:
        return _effect(
            fields,
            outcome.status,
            outcome.error_code or "CREATE_FAILED",
            outcome.message or NOT_DISPATCHED_MESSAGE,
        )
    if outcome.recovered:
        fields["recovered"] = "true"
    if run.read is None:
        fields["verified"] = "false"
    else:
        fields.update(_observed_fields(run))
    return MetaAdsMutationEffect(
        fields=freeze_fields(fields), outcome="applied", external_ref=outcome.object_id
    )


def _interrupted_effect(run: AdRun, fields: Mapping[str, str]) -> MetaAdsMutationEffect:
    # A create already handed to Meta might exist; one never sent doesn't.
    if run.sending:
        return _effect(
            fields,
            "unverified",
            "CREATE_NOT_CONFIRMED",
            "Meta Ads didn't confirm this was created. Check Ads Manager.",
        )
    return _effect(fields, "failed", NOT_DISPATCHED_CODE, NOT_DISPATCHED_MESSAGE)


def _observed_fields(run: AdRun) -> dict[str, str]:
    row = run.read or {}
    observed: dict[str, str] = {}
    creative = row.get("creative")
    creative_id = creative.get("id") if isinstance(creative, Mapping) else None
    if isinstance(creative_id, str) and creative_id.isascii() and creative_id.isdigit():
        observed["creative_id"] = creative_id[:128]
    if isinstance(row.get("effective_status"), str) and row["effective_status"]:
        observed["effective_status"] = row["effective_status"][:64]
    if unexpected := unexpected_changes(run):
        observed["unexpected_changes"] = ",".join(sorted(unexpected))
    return observed


def unexpected_changes(run: AdRun) -> frozenset[str]:
    """Returns automatic changes Meta shows on that the approval left off for this ad."""
    creative = (run.read or {}).get("creative")
    if not isinstance(creative, Mapping):
        return frozenset()
    return applied_changes(creative) - run.ad.enabled


def ad_row(run: AdRun) -> dict[str, Any]:
    """Builds one result row from what the run proved."""
    effect = ad_effect(run)
    observed = dict(effect.fields)
    row = run.read or {}
    effective_status = observed.get("effective_status")
    unexpected = unexpected_changes(run)
    message = effect.message
    if effect.outcome == "applied":
        if unexpected:
            message = _UNEXPECTED_CHANGES.format(labels=", ".join(change_labels(unexpected)))
        elif run.read is None:
            message = _READBACK_FAILED
    return {
        "design_index": run.ad.design_index,
        "name": run.ad.name,
        "adset_id": run.ad.adset_id,
        "adset_name": run.ad.adset_name,
        "format": run.ad.design.format,
        "requested_status": run.ad.status,
        "outcome": {"applied": "created"}.get(effect.outcome, effect.outcome),
        "recovered": observed.get("recovered") == "true",
        "verified": effect.outcome == "applied" and run.read is not None,
        "ad_id": effect.external_ref,
        "creative_id": observed.get("creative_id"),
        "effective_status": effective_status,
        "review": review_state(effective_status) if run.read else "unknown",
        "review_reasons": review_reasons(row),
        "unexpected_changes": change_labels(unexpected),
        "preview_url": preview_url(row.get("preview_shareable_link")),
        "error_code": effect.error_code,
        "message": message,
    }


def preview_url(value: Any) -> str | None:
    """Keeps Meta's preview link only when it's https on Facebook's own hosts."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    has_userinfo = parts.username is not None or parts.password is not None
    return (
        value if parts.scheme == "https" and host in _PREVIEW_HOSTS and not has_userinfo else None
    )
