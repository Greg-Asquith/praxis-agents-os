# apps/api/integrations/airtable/references.py

"""Canonical Airtable record reference construction."""

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field

from services.agents.runtime.untrusted import is_untrusted_content, untrusted_content_text
from services.integrations.entity_references import ScopedEntityReference


class AirtableRecordReference(ScopedEntityReference):
    entity_kind: Literal["airtable_record"] = "airtable_record"
    table: str = Field(min_length=1, max_length=256)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "table",
    )


def airtable_tables_match(left: str, right: str) -> bool:
    """Compare table names or ids without cosmetic casing or surrounding whitespace."""
    return left.strip().casefold() == right.strip().casefold()


def _record_label_text(value: Any) -> str | None:
    if is_untrusted_content(value):
        return untrusted_content_text(value) or None
    if isinstance(value, Mapping):
        for item in value.values():
            if text := _record_label_text(item):
                return text
    if isinstance(value, list):
        for item in value:
            if text := _record_label_text(item):
                return text
    if isinstance(value, (str, int, float)):
        return untrusted_content_text(value) or None
    return None


def airtable_record_reference(
    entry,
    table: str,
    record: Mapping[str, Any],
) -> AirtableRecordReference | None:
    record_id = str(record.get("record_id", "")).strip()
    if not record_id:
        return None
    fields = record.get("fields")
    label = _record_label_text(fields) or "(unnamed record)"
    return AirtableRecordReference(
        integration_resource_id=entry.integration_resource_id,
        external_id=record_id,
        label=label[:500],
        description=f"Record in {table}",
        scope_label=entry.display_name,
        table=table,
    )
