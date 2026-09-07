# apps/api/core/settings/microsoft_graph.py

"""Microsoft Graph integration settings."""

from pydantic import Field


class MicrosoftGraphSettingsMixin:
    MICROSOFT_GRAPH_TENANT: str = ""
    MICROSOFT_GRAPH_REQUESTS_PER_SECOND: float = Field(default=4.0, ge=0.5, le=20.0)
