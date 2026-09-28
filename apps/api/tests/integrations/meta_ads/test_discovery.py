"""Checks account discovery and conservative write permissions."""

from pathlib import Path

import httpx2
import pytest

from integrations.meta_ads.discover_resources import discover_resources
from tests.integrations.meta_ads.support import (
    TOKEN,
    DiscoveryTransport,
    account,
    install_transport,
)

HOSTILE_LABEL = (
    Path(__file__).resolve().parents[2] / "fixtures/prompt_injection/hostile_search_console_row.txt"
)


@pytest.mark.parametrize("task", ["MANAGE", "ADVERTISE", "ANALYZE"])
@pytest.mark.parametrize("permission", ["granted", "declined"])
async def test_writability_requires_both_account_task_and_token_permission(
    monkeypatch, task, permission
) -> None:
    transport = DiscoveryTransport([[account(user_tasks=[task])]], permission_status=permission)
    install_transport(monkeypatch, transport)
    result = (await discover_resources(TOKEN)).resources
    assert result[0].writable is (permission == "granted" and task in {"MANAGE", "ADVERTISE"})
    assert sum(request.url.path.endswith("/permissions") for request in transport.requests) == 1


async def test_discovery_sorts_deduplicates_and_records_full_metadata(monkeypatch) -> None:
    transport = DiscoveryTransport(
        [[account("2", name="zebra"), account("1", name="Alpha")], [account("2")]]
    )
    install_transport(monkeypatch, transport)
    result = (await discover_resources(TOKEN)).resources
    assert [item.external_id for item in result] == ["1", "2"]
    assert all(item.resource_type == "meta_ads_ad_account" for item in result)
    assert all(item.parent_external_id is None for item in result)
    assert all(item.required_write_scopes == () for item in result)
    assert result[0].permissions_metadata == {
        "currency": "GBP",
        "timezone_name": "Europe/London",
        "account_status": "ACTIVE",
        "business_id": "",
        "business_name": "",
        "tasks": ["MANAGE"],
        "token_permissions": ["ads_management", "ads_read"],
    }
    account_requests = [r for r in transport.requests if r.url.path.endswith("/adaccounts")]
    assert len(account_requests) == 2
    assert account_requests[0].url.params["limit"] == "100"
    assert all("business" not in request.url.params["fields"] for request in account_requests)
    assert "user_tasks" in account_requests[0].url.params["fields"]


@pytest.mark.parametrize(
    "status",
    [
        2,
    ],
)
async def test_non_active_accounts_remain_read_only(monkeypatch, status) -> None:
    install_transport(monkeypatch, DiscoveryTransport([[account(account_status=status)]]))
    result = (await discover_resources(TOKEN)).resources
    assert len(result) == 1
    assert result[0].writable is False
    assert isinstance(result[0].permissions_metadata["account_status"], str)


async def test_rediscovery_rechecks_removed_permissions(monkeypatch) -> None:
    transport = DiscoveryTransport([[account()]])
    install_transport(monkeypatch, transport)
    assert (await discover_resources(TOKEN)).resources[0].writable
    transport.permission_status = "declined"
    assert not (await discover_resources(TOKEN)).resources[0].writable


@pytest.mark.parametrize(
    "tasks",
    [
        None,
        "MANAGE",
    ],
)
async def test_absent_or_malformed_tasks_never_grant_writes(monkeypatch, tasks) -> None:
    install_transport(monkeypatch, DiscoveryTransport([[account(user_tasks=tasks)]]))
    assert not (await discover_resources(TOKEN)).resources[0].writable


async def test_conflicting_duplicate_permissions_fail_closed(monkeypatch) -> None:
    install_transport(
        monkeypatch,
        DiscoveryTransport([[account()], [account(user_tasks=["ANALYZE"])]]),
    )
    result = await discover_resources(TOKEN)
    assert len(result.resources) == 1
    assert not result.resources[0].writable


@pytest.mark.parametrize(
    ("task", "permission"),
    [
        ("MANAGE", "declined"),
    ],
)
async def test_hostile_account_labels_remain_data_without_granting_writes(
    monkeypatch, task, permission
) -> None:
    hostile = HOSTILE_LABEL.read_text(encoding="utf-8").strip()
    install_transport(
        monkeypatch,
        DiscoveryTransport(
            [[account(name=hostile, user_tasks=[task])]],
            permission_status=permission,
        ),
    )
    resource = (await discover_resources(TOKEN)).resources[0]
    assert resource.display_name == hostile
    assert resource.permissions_metadata["tasks"] == [task]
    assert resource.external_id == "123"
    assert resource.writable is False


async def test_permission_page_cap_disables_writes_despite_granted_first_page(monkeypatch) -> None:
    class PagedPermissions(DiscoveryTransport):
        def handle(self, request: httpx2.Request) -> httpx2.Response:
            if not request.url.path.endswith("/me/permissions"):
                return super().handle(request)
            self.requests.append(request)
            page = int(request.url.params.get("after", "0"))
            return httpx2.Response(
                200,
                json={
                    "data": [{"permission": "ads_management", "status": "granted"}],
                    "paging": {
                        "next": f"https://graph.facebook.com/v26.0/me/permissions?after={page + 1}"
                    },
                },
                request=request,
            )

    transport = PagedPermissions([[account()]])
    install_transport(monkeypatch, transport)
    result = await discover_resources(TOKEN)
    assert result.degraded_reason == "page_cap"
    assert len(result.resources) == 1
    assert result.resources[0].permissions_metadata["token_permissions"] == ["ads_management"]
    assert result.resources[0].writable is False
    assert sum(request.url.path.endswith("/permissions") for request in transport.requests) == 20
