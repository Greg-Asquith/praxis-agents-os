# apps/api/integrations/google_ads/tools/utils/negative_keyword_evidence.py

"""Exact outcome attribution for campaign and ad-group negative keywords."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

type NegativeKeywordAction = Literal["add", "remove"]
type KeywordOutcome = dict[str, str]

_MATCH_TYPE_ORDER = {"EXACT": 0, "PHRASE": 1, "BROAD": 2, "ANY": 3}


def exact_negative_keyword_outcomes(
    *,
    action: NegativeKeywordAction,
    entity_id_key: str,
    entity_ids: Sequence[str],
    keywords: Sequence[Mapping[str, str]],
    result: Mapping[str, Any],
    errors_key: str,
) -> dict[str, list[KeywordOutcome]]:
    """Validate and order every provider-accounted target-keyword outcome."""
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    requested_ids = set(entity_ids)
    requested_keywords = [_keyword_pair(keyword) for keyword in keywords]
    if not requested_ids or len(requested_ids) != len(entity_ids) or not requested_keywords:
        raise ValueError("Negative keyword evidence requires unique targets and keywords")

    buckets = (
        (applied_key, applied_key),
        (skipped_key, skipped_key),
        (errors_key, "failed"),
    )
    outcomes: dict[str, list[KeywordOutcome]] = {entity_id: [] for entity_id in entity_ids}
    seen: set[tuple[str, str, str]] = set()
    indexed: dict[tuple[str, str], list[KeywordOutcome]] = {}

    applied_rows = _rows(result, applied_key)
    resource_names = result.get("resource_names")
    if not isinstance(resource_names, list) or len(resource_names) != len(applied_rows):
        raise ValueError("Applied negative keyword rows do not match provider resource names")

    for bucket_key, outcome in buckets:
        for row in _rows(result, bucket_key):
            entity_id = _required_string(row, entity_id_key)
            text, match_type = _keyword_pair(row)
            if entity_id not in requested_ids or not _was_requested(
                text=text,
                match_type=match_type,
                requested=requested_keywords,
            ):
                raise ValueError("Provider returned an unknown negative keyword outcome")
            identity = (entity_id, text.casefold(), match_type)
            if identity in seen:
                raise ValueError("Provider returned a duplicate negative keyword outcome")
            seen.add(identity)
            evidence: KeywordOutcome = {
                "text": text,
                "match_type": match_type,
                "outcome": outcome,
            }
            if outcome == applied_key:
                resource_name = _required_string(row, "resource_name")
                evidence["external_ref"] = resource_name
            elif outcome == "failed":
                evidence["error_code"] = _required_string(row, "error_code")[:100]
            indexed.setdefault((entity_id, text.casefold()), []).append(evidence)

    for index, row in enumerate(applied_rows):
        if _required_string(row, "resource_name") != resource_names[index]:
            raise ValueError("Applied negative keyword resource attribution is inconsistent")

    for entity_id in entity_ids:
        for requested_text, requested_match_type in requested_keywords:
            matching = [
                item
                for item in indexed.get((entity_id, requested_text.casefold()), [])
                if requested_match_type == "ANY" or item["match_type"] == requested_match_type
            ]
            if not matching:
                raise ValueError("Provider did not account for a requested negative keyword")
            if requested_match_type != "ANY" and len(matching) != 1:
                raise ValueError("Provider returned contradictory negative keyword outcomes")
            matching.sort(key=lambda item: _MATCH_TYPE_ORDER[item["match_type"]])
            outcomes[entity_id].extend(matching)

    accounted = sum(len(items) for items in outcomes.values())
    if accounted != len(seen):
        raise ValueError("Provider negative keyword outcomes could not be attributed exactly")
    return outcomes


def _rows(result: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = result.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"Negative keyword result field {key!r} is invalid")
    return value


def _keyword_pair(value: Mapping[str, Any]) -> tuple[str, str]:
    text = _required_string(value, "text")
    match_type = _required_string(value, "match_type")
    if match_type not in _MATCH_TYPE_ORDER:
        raise ValueError("Negative keyword match type is invalid")
    return text, match_type


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Negative keyword outcome field {key!r} is invalid")
    return item


def _was_requested(
    *,
    text: str,
    match_type: str,
    requested: Sequence[tuple[str, str]],
) -> bool:
    return any(
        text.casefold() == requested_text.casefold()
        and (requested_match_type == "ANY" or requested_match_type == match_type)
        for requested_text, requested_match_type in requested
    )
