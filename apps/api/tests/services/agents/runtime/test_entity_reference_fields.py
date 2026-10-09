"""Which entity kinds a tool field lets the browser look up."""

from services.agents.runtime.entity_references.service import _field_entity_kind
from services.agents.runtime.tools.contract import ToolFieldPresentation


def test_lookups_reach_only_the_kinds_a_field_declares():
    structured = ToolFieldPresentation(
        key="ads", label="Ads", format="structured", entity_kinds=("meta_ads_media", "file")
    )
    entity = ToolFieldPresentation(key="page", label="Page", format="entity", entity_kind="page")

    assert _field_entity_kind(structured, "file") == "file"
    assert _field_entity_kind(structured, "meta_ads_page") is None
    assert _field_entity_kind(structured, None) is None
    assert _field_entity_kind(entity, None) == "page"
    assert _field_entity_kind(entity, "file") is None
