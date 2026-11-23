# apps/api/core/settings/web.py

"""Limits and the domain denylist for the agent web tools."""

import re

from pydantic import Field, field_validator

_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class WebFetchSettingsMixin:
    WEB_FETCH_BLOCKED_DOMAINS: str = Field(
        default="",
        description=(
            "Comma-separated domains the web tools refuse, including their subdomains. "
            "While set, ask_url only offers providers that enforce domain filtering."
        ),
    )
    WEB_FETCH_TIMEOUT_SECONDS: float = Field(
        default=20.0,
        gt=0,
        le=120,
        description="Total time for one web fetch, including redirects, reading, and conversion.",
    )
    WEB_FETCH_MAX_REDIRECTS: int = Field(
        default=10,
        ge=0,
        le=20,
        description="Maximum redirects one web fetch follows.",
    )
    WEB_FETCH_MAX_BYTES: int = Field(
        default=5 * 1024 * 1024,
        gt=0,
        le=20 * 1024 * 1024,
        description="Maximum decoded response bytes one web fetch reads.",
    )
    WEB_FETCH_HOST_CONCURRENCY: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Requests one agent run sends to a single host at once.",
    )
    WEB_FETCH_RUN_URL_BUDGET: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="URLs one agent run can fetch across the web tools.",
    )

    @field_validator("WEB_FETCH_BLOCKED_DOMAINS")
    @classmethod
    def validate_web_fetch_blocked_domains(cls, value: str) -> str:
        domains = tuple(
            dict.fromkeys(domain.strip().lower().rstrip(".") for domain in value.split(","))
        )
        invalid = [domain for domain in domains if domain and not _DOMAIN_PATTERN.fullmatch(domain)]
        if invalid:
            raise ValueError(
                "WEB_FETCH_BLOCKED_DOMAINS entries must be bare domain names: " + ", ".join(invalid)
            )
        return ",".join(domain for domain in domains if domain)
