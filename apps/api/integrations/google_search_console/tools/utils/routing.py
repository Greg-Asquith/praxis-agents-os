# apps/api/integrations/google_search_console/tools/utils/routing.py

"""Route requested URLs to selected Search Console properties."""

from collections.abc import Sequence
from urllib.parse import SplitResult, urlsplit

from pydantic_ai import ModelRetry

from integrations.google_search_console.references import (
    MAX_SEARCH_CONSOLE_URL_LENGTH,
    GoogleSearchConsoleUrlReference,
)
from services.integrations.context.domain import ResolvedContextEntry


def url_references_for_entries(
    entries: Sequence[ResolvedContextEntry],
    urls: Sequence[str],
) -> list[GoogleSearchConsoleUrlReference]:
    """Return one ordered scoped reference per valid, uniquely requested URL."""
    if not urls:
        raise ModelRetry("Provide at least one URL to inspect.")
    if len(urls) > 10:
        raise ModelRetry("Inspect no more than 10 URLs at a time.")
    normalized_urls: list[tuple[str, SplitResult]] = []
    seen: set[str] = set()
    for value in urls:
        url = value.strip()
        if len(url) > MAX_SEARCH_CONSOLE_URL_LENGTH:
            raise ModelRetry(
                f"Each URL must contain no more than {MAX_SEARCH_CONSOLE_URL_LENGTH:,} characters."
            )
        parsed = urlsplit(url)
        if not _valid_http_url(parsed):
            raise ModelRetry(f"{value!r} is not a valid HTTP or HTTPS URL without credentials.")
        if url in seen:
            raise ModelRetry(f"The URL {url!r} was provided more than once.")
        seen.add(url)
        normalized_urls.append((url, parsed))

    references: list[GoogleSearchConsoleUrlReference] = []
    for url, parsed in normalized_urls:
        entry = _matching_entry(entries, parsed)
        if entry is None:
            raise ModelRetry(
                f"The URL {url!r} does not match a selected Search Console property. "
                "Ask the user to select its property and try again."
            )
        references.append(
            GoogleSearchConsoleUrlReference(
                site_url=entry.external_id,
                url=url,
                label=url[:500],
                description="Search Console URL",
                scope_label=entry.display_name,
            )
        )
    return references


def _matching_entry(
    entries: Sequence[ResolvedContextEntry],
    url: SplitResult,
) -> ResolvedContextEntry | None:
    prefix_matches: list[tuple[int, ResolvedContextEntry]] = []
    domain_matches: list[ResolvedContextEntry] = []
    hostname = (url.hostname or "").lower()
    for entry in entries:
        site_url = entry.external_id
        if site_url.startswith("sc-domain:"):
            domain = site_url.removeprefix("sc-domain:").lower()
            if hostname == domain or hostname.endswith(f".{domain}"):
                domain_matches.append(entry)
            continue
        site = urlsplit(site_url)
        if (
            site.scheme.lower() == url.scheme.lower()
            and (site.hostname or "").lower() == hostname
            and site.port == url.port
            and url.path.startswith(site.path)
        ):
            prefix_matches.append((len(site_url), entry))
    if prefix_matches:
        return max(prefix_matches, key=lambda item: item[0])[1]
    return domain_matches[0] if domain_matches else None


def _valid_http_url(value: SplitResult) -> bool:
    try:
        valid_port = value.port is None or value.port > 0
    except ValueError:
        return False
    return (
        valid_port
        and value.scheme.lower() in {"http", "https"}
        and bool(value.hostname)
        and value.username is None
        and value.password is None
    )
