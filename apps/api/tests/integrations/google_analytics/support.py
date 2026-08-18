"""Shared builders for Google Analytics integration tests."""

from uuid import uuid4

from services.integrations.context.domain import ResolvedContextEntry


async def static_token(_force: bool) -> str:
    return "access-token"


def property_entry() -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_analytics",
        resource_type="google_analytics_property",
        external_id="123456",
        display_name="Website",
        connection_id=uuid4(),
        connection_label="Client analytics",
        connection_status="active",
        write_allowed=False,
    )
