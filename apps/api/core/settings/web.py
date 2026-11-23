# apps/api/core/settings/web.py

"""Limits, the domain denylist, and the PageSpeed Insights key for the agent web tools."""

import re

from pydantic import Field, SecretStr, field_validator

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
        default=5,
        ge=1,
        le=10,
        description="Requests one agent run sends to a single host at once.",
    )
    WEB_FETCH_RUN_URL_BUDGET: int = Field(
        default=5_000,
        ge=1,
        le=50_000,
        description="URLs one agent run can fetch across the web tools.",
    )
    WEB_FETCH_MAX_URLS_PER_CALL: int = Field(
        default=500,
        ge=1,
        le=1_000,
        description="URLs one check_urls call checks.",
    )
    WEB_FETCH_BATCH_DEADLINE_SECONDS: float = Field(
        default=120.0,
        gt=0,
        le=240,
        description=(
            "Total time for one check_urls call; URLs it doesn't reach return not_checked. "
            "Stays under the Code Mode script timeout."
        ),
    )
    PAGESPEED_API_KEY: SecretStr | None = Field(
        default=None,
        description=(
            "Google API key restricted to the PageSpeed Insights API. measure_page_speed "
            "is available only while it's set."
        ),
    )
    PAGESPEED_TIMEOUT_SECONDS: float = Field(
        default=90.0,
        gt=0,
        le=120,
        description="Time for one PageSpeed Insights test.",
    )
    PAGESPEED_MAX_URLS_PER_CALL: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Pages one measure_page_speed call tests.",
    )
    PAGESPEED_BATCH_DEADLINE_SECONDS: float = Field(
        default=240.0,
        gt=0,
        le=270,
        description=(
            "Total time for one measure_page_speed call; pages it doesn't reach return "
            "not_checked. Stays under the Code Mode script timeout."
        ),
    )
    PAGESPEED_RUN_BUDGET: int = Field(
        default=200,
        ge=1,
        le=2_000,
        description="PageSpeed Insights tests one agent run can start.",
    )

    @field_validator("PAGESPEED_API_KEY")
    @classmethod
    def validate_pagespeed_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        # An empty deploy value means no key, so the tool stays unavailable.
        return value if value is not None and value.get_secret_value().strip() else None

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
