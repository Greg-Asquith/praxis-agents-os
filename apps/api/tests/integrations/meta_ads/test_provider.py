"""Checks the Meta package's limited provider surface."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.meta_ads import PROVIDER
from integrations.meta_ads.tools import TOOL_DEFINITIONS
from integrations.meta_ads.tools.utils.bindings import META_ADS_BINDING, META_ADS_WRITE_BINDING
from services.agents.runtime.tools.contract import VALID_TOOL_ICONS
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.execution import _run_authorized_entries


def test_provider_contract_exposes_workspace_token_discovery_and_insights() -> None:
    manifest = PROVIDER.manifest
    assert manifest.provider_key == "meta_ads"
    assert manifest.display_name == "Meta Ads"
    assert manifest.auth_modes == ("api_key",)
    assert manifest.owner_scope == "workspace"
    assert manifest.resource_types == ("meta_ads_ad_account",)
    assert manifest.required_form_fields == ("access_token",)
    assert manifest.requires_discovery is True
    assert manifest.capability_flags == frozenset({"read", "write", "spend"})
    assert manifest.event_delivery == "none"
    assert PROVIDER.tool_definitions == TOOL_DEFINITIONS
    assert [tool.name for tool in TOOL_DEFINITIONS] == [
        "meta_ads_run_insights",
        "meta_ads_get_accounts",
        "meta_ads_list_objects",
        "meta_ads_list_custom_conversions",
    ]
    assert "meta_ads" in VALID_TOOL_ICONS


def test_write_binding_requires_write_permission() -> None:
    assert META_ADS_BINDING.provider_keys == frozenset({"meta_ads"})
    assert META_ADS_BINDING.resource_types == frozenset({"meta_ads_ad_account"})
    assert META_ADS_BINDING.requires_write is False
    assert META_ADS_WRITE_BINDING.provider_keys == META_ADS_BINDING.provider_keys
    assert META_ADS_WRITE_BINDING.resource_types == META_ADS_BINDING.resource_types
    assert META_ADS_WRITE_BINDING.requires_write is True


async def test_read_only_account_cannot_execute_write_binding(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="meta_ads",
        resource_type="meta_ads_ad_account",
        external_id="123",
        display_name="Reporting account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"tasks": ["ANALYZE"]},
    )
    monkeypatch.setattr(
        "services.integrations.operations._resolve_dispatched_integration_definition",
        lambda _ctx: SimpleNamespace(integration_binding=META_ADS_WRITE_BINDING),
    )
    denial = AsyncMock()
    monkeypatch.setattr("services.integrations.operations.record_integration_write_denial", denial)
    operation = AsyncMock()
    ctx = object()
    result = await _run_authorized_entries(
        ctx, binding=META_ADS_WRITE_BINDING, selected=[(entry, None)], operation=operation
    )
    assert result[0].error_code == "write_not_permitted"
    operation.assert_not_awaited()
    denial.assert_awaited_once_with(ctx, entry)
