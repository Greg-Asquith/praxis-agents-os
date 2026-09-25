"""Builds bounded Meta responses without live credentials."""

from typing import Any
from uuid import uuid4

import httpx2

from services.integrations.context.domain import ResolvedContextEntry

TOKEN = "meta-test-access-token"


def context_entry(account_id: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="meta_ads",
        resource_type="meta_ads_ad_account",
        external_id=account_id,
        display_name=f"Account {account_id}",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"currency": "EUR", "timezone_name": "Europe/Paris"},
    )


async def static_token() -> str:
    return TOKEN


def account(account_id: str = "123", **overrides: Any) -> dict[str, Any]:
    return {
        "id": f"act_{account_id}",
        "account_id": account_id,
        "name": f"Account {account_id}",
        "currency": "GBP",
        "timezone_name": "Europe/London",
        "account_status": 1,
        "user_tasks": ["MANAGE"],
        **overrides,
    }


class DiscoveryTransport(httpx2.MockTransport):
    def __init__(
        self,
        pages: list[list[dict[str, Any]]] | None = None,
        *,
        permission_status: str = "granted",
        identity: dict[str, Any] | None = None,
    ) -> None:
        self.pages = pages if pages is not None else [[account("2")], [account("1")]]
        self.permission_status = permission_status
        self.identity = identity if identity is not None else {"id": "700", "name": "Agent"}
        self.requests: list[httpx2.Request] = []
        super().__init__(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.endswith("/me/permissions"):
            payload = {
                "data": [
                    {"permission": "ads_read", "status": "granted"},
                    {"permission": "ads_management", "status": self.permission_status},
                ]
            }
        elif request.url.path.endswith("/me/adaccounts"):
            page = int(request.url.params.get("after", "0"))
            payload = {"data": self.pages[page]}
            if page + 1 < len(self.pages):
                payload["paging"] = {
                    "next": f"https://graph.facebook.com/v26.0/me/adaccounts?after={page + 1}"
                }
        else:
            assert request.url.path.endswith("/me")
            payload = self.identity
        return httpx2.Response(200, json=payload, request=request)


def install_transport(monkeypatch, transport: DiscoveryTransport) -> None:
    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        "services.integrations.http.httpx2.AsyncClient",
        lambda: original_client(transport=transport),
    )
