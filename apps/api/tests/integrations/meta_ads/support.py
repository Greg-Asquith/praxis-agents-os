"""Builds bounded Meta responses without live credentials."""

import json
from typing import Any
from urllib.parse import parse_qsl
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
    """Serves the account, its edges, and its history from memory, and applies posted changes."""

    def __init__(self, objects, *, post=None, account=None, activities=None):
        self.objects = {item["id"]: {"status": "PAUSED", **item} for item in objects}
        self.post = post or {}
        self.account = {"currency": "EUR", "account_status": 1, **(account or {})}
        self.activities = activities or []
        self.posts: list[str] = []
        self.dry_runs: list[str] = []
        self.sent: list[dict[str, str]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method == "POST":
            return self.handle_post(request, path[0])
        if len(path) == 1:
            return httpx2.Response(200, json=self.account, request=request)
        if path[1] == "activities":
            return httpx2.Response(200, json={"data": self.activities}, request=request)
        object_type = GRAPH_EDGES[path[1]]
        filters = json.loads(request.url.params["filtering"])
        rows = [item for item in self.objects.values() if matches(item, object_type, filters)]
        return httpx2.Response(200, json={"data": rows}, request=request)

    def handle_post(self, request: httpx2.Request, object_id: str) -> httpx2.Response:
        form = dict(parse_qsl(request.content.decode()))
        behaviour = self.post.get(object_id, "apply")
        if "execution_options" in form:
            self.dry_runs.append(object_id)
            if behaviour == "reject_dry_run":
                error = {"code": 100, "error_user_msg": "The budget is too low.", "fbtrace_id": "t"}
                return httpx2.Response(400, json={"error": error}, request=request)
            confirmed = behaviour != "unconfirmed_dry_run"
            return httpx2.Response(200, json={"success": confirmed}, request=request)
        self.posts.append(object_id)
        self.sent.append(form)
        if behaviour == "timeout":
            raise httpx2.ReadTimeout("lost", request=request)
        if behaviour == "throttle":
            error = {"code": 613, "error_subcode": 1487632, "fbtrace_id": "trace"}
            return httpx2.Response(400, json={"error": error}, request=request)
        if behaviour == "apply_as_lifetime":
            self.objects[object_id].pop("daily_budget", None)
            self.objects[object_id]["lifetime_budget"] = form["daily_budget"]
        if behaviour == "apply":
            for key in ("status", "daily_budget", "lifetime_budget"):
                if key in form:
                    self.objects[object_id][key] = form[key]
            self.hold_children()
        return httpx2.Response(200, json={"success": True}, request=request)

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
