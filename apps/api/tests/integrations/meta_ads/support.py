"""Builds bounded Meta responses without live credentials."""

import json
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


GRAPH_EDGES = {"campaigns": "campaign", "adsets": "adset", "ads": "ad"}


class FakeGraph:
    """Serves account edges from in-memory objects and applies status posts."""

    def __init__(self, objects, *, post=None):
        self.objects = {item["id"]: {"status": "PAUSED", **item} for item in objects}
        self.post = post or {}
        self.posts: list[str] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method == "POST":
            object_id = path[0]
            self.posts.append(object_id)
            behaviour = self.post.get(object_id, "apply")
            if behaviour == "timeout":
                raise httpx2.ReadTimeout("lost", request=request)
            if behaviour == "throttle":
                error = {"code": 613, "error_subcode": 1487632, "fbtrace_id": "trace"}
                return httpx2.Response(400, json={"error": error}, request=request)
            if behaviour == "apply":
                self.objects[object_id]["status"] = parse_status(request)
                self.hold_children()
            return httpx2.Response(200, json={"success": True}, request=request)
        object_type = GRAPH_EDGES[path[1]]
        filters = json.loads(request.url.params["filtering"])
        rows = [item for item in self.objects.values() if matches(item, object_type, filters)]
        return httpx2.Response(200, json={"data": rows}, request=request)

    def hold_children(self):
        """Shows a parent that is off as the delivery status of its children that are on."""
        for item in self.objects.values():
            if item["status"] != "ACTIVE":
                continue
            held = [
                f"{kind}_PAUSED"
                for kind, key in (("ADSET", "adset_id"), ("CAMPAIGN", "campaign_id"))
                if key in item and self.objects[item[key]]["status"] != "ACTIVE"
            ]
            item["effective_status"] = held[-1] if held else "ACTIVE"


def parse_status(request: httpx2.Request) -> str:
    return dict(item.split("=") for item in request.content.decode().split("&"))["status"]


def matches(item, object_type, filters) -> bool:
    if item["type"] != object_type:
        return False
    for rule in filters:
        field = {"campaign.id": "campaign_id", "adset.id": "adset_id"}.get(
            rule["field"], rule["field"]
        )
        if rule["operator"] == "IN" and item.get(field) not in rule["value"]:
            return False
    return True


def obj(object_id, object_type, **fields):
    return {
        "id": object_id,
        "type": object_type,
        "name": f"{object_type} {object_id}",
        "effective_status": fields.get("status", "PAUSED"),
        **fields,
    }
