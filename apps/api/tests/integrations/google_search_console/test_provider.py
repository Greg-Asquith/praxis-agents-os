# apps/api/tests/integrations/google_search_console/test_provider.py

"""Google Search Console provider manifest contracts."""

from integrations.google_search_console import _oauth_scopes
from integrations.google_search_console.discover_resources import INDEXING_SCOPE, WEBMASTERS_SCOPE


def test_indexing_scope_is_requested_only_when_the_operator_setting_is_on(monkeypatch) -> None:
    monkeypatch.setattr(
        "integrations.google_search_console.settings.google_search_console_settings.GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED",
        False,
    )
    assert _oauth_scopes() == ("openid", "email", WEBMASTERS_SCOPE)

    monkeypatch.setattr(
        "integrations.google_search_console.settings.google_search_console_settings.GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED",
        True,
    )
    assert _oauth_scopes() == ("openid", "email", WEBMASTERS_SCOPE, INDEXING_SCOPE)
