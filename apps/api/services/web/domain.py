# apps/api/services/web/domain.py

"""Records and errors for public-web fetches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.exceptions.general import AppValidationError

UserAgent = Literal[
    "praxis",
    "desktop_browser",
    "mobile_browser",
    "googlebot_desktop",
    "googlebot_mobile",
]
USER_AGENT_HEADERS: dict[UserAgent, str] = {
    "praxis": "Praxis-Agents-Fetch/1.0 (+https://www.praxis-agents.ai/)",
    "desktop_browser": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    "mobile_browser": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1"
    ),
    "googlebot_desktop": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html) Chrome/142.0.0.0 Safari/537.36"
    ),
    "googlebot_mobile": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
}

# "success" skips the body of non-2xx responses; "none" closes the stream after headers.
BodyMode = Literal["always", "success", "none"]

WebFetchErrorClass = Literal[
    "invalid_url",
    "unsupported_port",
    "non_public_address",
    "blocked_domain",
    "dns_failure",
    "tls_failure",
    "connect_failure",
    "protocol_failure",
    "timeout",
    "redirect_without_location",
    "too_many_redirects",
    "too_large",
]

RESPONSE_HEADER_ALLOWLIST = (
    "cache-control",
    "cf-mitigated",
    "content-language",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "link",
    "location",
    "retry-after",
    "server",
    "strict-transport-security",
    "x-amzn-waf-action",
    "x-robots-tag",
)
_CHALLENGE_STATUSES = frozenset({403, 429, 503})
_CHALLENGE_HEADERS = ("cf-mitigated", "x-amzn-waf-action")


@dataclass(frozen=True)
class RedirectHop:
    """One redirect response: the URL requested, its status, and the resolved target."""

    url: str
    status: int
    location: str


@dataclass(frozen=True)
class FetchedResponse:
    """The final response of one fetch, with every redirect followed to reach it."""

    requested_url: str
    final_url: str
    status: int
    headers: dict[str, str]
    redirects: tuple[RedirectHop, ...]
    user_agent: UserAgent
    body: bytes
    body_read: bool
    gunzipped: bool
    time_to_first_byte_ms: int
    elapsed_ms: int

    @property
    def content_type(self) -> str:
        """Returns the response content type, or a binary default when absent."""
        return self.headers.get("content-type", "application/octet-stream")

    @property
    def blocked_by_site(self) -> bool:
        """Checks whether the site answered with a known automated-request challenge."""
        return self.status in _CHALLENGE_STATUSES and any(
            header in self.headers for header in _CHALLENGE_HEADERS
        )


class WebFetchError(AppValidationError):
    """Raised when a fetch fails before a final response is available."""

    def __init__(
        self,
        message: str,
        *,
        error_class: WebFetchErrorClass,
        redirects: tuple[RedirectHop, ...] = (),
    ) -> None:
        super().__init__(message, field="url", details={"error_class": error_class})
        self.error_class = error_class
        self.redirects = redirects
