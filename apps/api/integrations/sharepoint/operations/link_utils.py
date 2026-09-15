# apps/api/integrations/sharepoint/operations/link_utils.py

"""Validates SharePoint links and bounds library recovery hints."""

import re
from urllib.parse import SplitResult, quote, unquote, urlsplit

from core.exceptions.integration import IntegrationValidationError
from services.agents.runtime.untrusted import UntrustedNode

from .utils import item_path, untrusted


class LibraryNotSelectedError(IntegrationValidationError):
    """Retains library provenance for failed link results and Code Mode."""

    def __init__(self, library: UntrustedNode):
        self.library = library
        super().__init__(
            "The linked library is not selected. Select the named site and library "
            "in the SharePoint connection and Active Context. "
            "Refresh discovery first if it is not listed.",
            provider_key="sharepoint",
            operation="open_link",
            error_code="library_not_selected",
        )


def link_error(message: str, code: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        message, provider_key="sharepoint", operation="open_link", error_code=code
    )


def sharepoint_url(value: str) -> SplitResult:
    try:
        url = urlsplit(value)
        valid = (
            len(value) <= 8192
            and url.scheme == "https"
            and re.fullmatch(r"[a-z0-9-]+\.sharepoint\.com", url.hostname or "")
            and url.username is None
            and url.password is None
            and url.port in (None, 443)
            and "\\" not in value
            and not any(ord(char) <= 32 or ord(char) == 127 for char in value)
        )
    except ValueError:
        valid = False
    if not valid:
        raise link_error(
            "Use an HTTPS file link from SharePoint or OneDrive for work.", "link_not_supported"
        )
    return url


def direct_link_path(url: str, drives: dict[str, str]) -> tuple[str, str] | None:
    """Finds the longest selected library prefix before any provider request."""
    target = sharepoint_url(url)
    target_parts = link_path_parts(target.path)
    if (
        len(target_parts) >= 2
        and target_parts[-2].casefold() == "forms"
        and target_parts[-1].casefold().endswith(".aspx")
    ):
        raise link_error(
            "This is a SharePoint library view. Use the file or folder's direct SharePoint URL.",
            "link_not_supported",
        )
    matches = []
    for drive_id, base, parts in direct_link_candidates(drives):
        if target.hostname == base.hostname and target_parts[: len(parts)] == parts:
            relative = "/".join(quote(part, safe="") for part in target_parts[len(parts) :])
            path = item_path(drive_id) + (f":/{relative}" if relative else "")
            matches.append((len(parts), drive_id, path))
    if not matches:
        return None
    longest = max(match[0] for match in matches)
    matches = [match for match in matches if match[0] == longest]
    if len(matches) != 1:
        raise link_error(
            "Select this library once, then try the link again.", "library_not_selected"
        )
    return matches[0][1:]


def direct_link_candidates(
    drives: dict[str, str],
) -> list[tuple[str, SplitResult, tuple[str, ...]]]:
    """Excludes unusable cached URLs without changing selected drive admission."""
    candidates = []
    for drive_id, web_url in drives.items():
        if not web_url:
            continue
        try:
            base = sharepoint_url(web_url)
            parts = link_path_parts(base.path)
        except IntegrationValidationError:
            continue
        candidates.append((drive_id, base, parts))
    return candidates


def link_path_parts(path: str) -> tuple[str, ...]:
    try:
        parts = tuple(unquote(part, errors="strict") for part in path.strip("/").split("/"))
    except UnicodeError:
        raise link_error("Use the file's direct SharePoint URL.", "link_not_supported") from None
    if any(
        part in {".", ".."}
        or any(char in part for char in ("/", "\\"))
        or any(ord(char) < 32 or ord(char) == 127 for char in part)
        for part in parts
    ):
        raise link_error("Use the file's direct SharePoint URL.", "link_not_supported")
    return parts if path.strip("/") else ()


def library_not_selected(item: dict) -> LibraryNotSelectedError:
    parent = item.get("parentReference", {})
    ids = item.get("sharepointIds", {})
    site = ids.get("siteUrl", "") if isinstance(ids, dict) else ""
    web_url = item.get("webUrl", "")
    site_name, library = "the linked site", "the linked library"
    try:
        site_url = sharepoint_url(site if isinstance(site, str) else "")
        file_url = sharepoint_url(web_url if isinstance(web_url, str) else "")
        site_parts = link_path_parts(site_url.path)
        file_parts = link_path_parts(file_url.path)
        site_name = site_parts[-1] if site_parts else site_url.hostname
        if file_url.hostname == site_url.hostname and file_parts[: len(site_parts)] == site_parts:
            library = file_parts[len(site_parts)]
    except (IntegrationValidationError, IndexError, TypeError, ValueError):
        pass
    drive_id = parent.get("driveId", "unknown") if isinstance(parent, dict) else "unknown"
    return LibraryNotSelectedError(
        untrusted(
            str(drive_id)[:100],
            str(item.get("id", "unknown"))[:100],
            f"{site_name} / {library}",
            160,
        )
    )
