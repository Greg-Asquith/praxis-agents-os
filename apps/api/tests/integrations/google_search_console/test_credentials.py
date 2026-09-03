"""Google Search Console runtime credential construction contracts."""

from types import SimpleNamespace
from uuid import uuid4

from integrations.google_search_console.tools.utils import client as client_module
from tests.integrations.google_search_console.support import site_entry


async def test_oauth_client_refreshes_through_the_shared_credential_seam(monkeypatch) -> None:
    credential = SimpleNamespace(auth_mode="oauth", id=uuid4())
    forces: list[bool] = []

    async def get_credential(*_args, **_kwargs):
        return credential

    async def ensure_fresh(*_args, force: bool, **_kwargs):
        forces.append(force)
        return SimpleNamespace(access_token="fresh-token")  # noqa: S106 -- test credential

    monkeypatch.setattr(client_module, "get_usable_connection_credential", get_credential)
    monkeypatch.setattr(client_module, "ensure_fresh_credential", ensure_fresh)
    client = await client_module.google_search_console_client_for_principal(
        object(),
        actor=SimpleNamespace(id=uuid4()),
        workspace=SimpleNamespace(id=uuid4()),
        entry=site_entry(),
    )

    assert await client._access_token(False) == "fresh-token"
    assert await client._access_token(True) == "fresh-token"
    assert forces == [False, True]
