# apps/api/integrations/google_search_console/references.py

"""Google Search Console scoped URL references."""

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference

MAX_SEARCH_CONSOLE_URL_LENGTH = 4_096


class GoogleSearchConsoleUrlReference(ScopedEntityReference):
    """A URL routed to one selected Search Console property."""

    entity_kind: Literal["google_search_console_url"] = "google_search_console_url"
    site_url: str = Field(min_length=1, max_length=1_000)
    url: str = Field(min_length=1, max_length=MAX_SEARCH_CONSOLE_URL_LENGTH)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "site_url",
        "url",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.site_url

    @property
    def provider_entity_id(self) -> str:
        return self.url
