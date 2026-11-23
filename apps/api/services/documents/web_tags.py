# apps/api/services/documents/web_tags.py

"""Finds analytics, advertising, and consent tags in a page's source. Imported only inside the worker.

Each pattern's first group, when it has one, is the tag ID. IDs match fixed character
classes, so they can't carry free text from the page.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

TagCategory = Literal["tag_manager", "analytics", "advertising", "experience", "consent"]
TagLocation = Literal["script_src", "inline_script", "noscript", "script_bundle"]

_MAX_TAGS = 100
# Bounds the regex work on one inline script; tag snippets sit near the start of their block.
_MAX_SCRIPT_SCAN_CHARS = 200_000


@dataclass(frozen=True)
class _TagPattern:
    vendor: str
    category: TagCategory
    pattern: re.Pattern[str]


def _tags(vendor: str, category: TagCategory, *patterns: str) -> tuple[_TagPattern, ...]:
    return tuple(_TagPattern(vendor, category, re.compile(pattern)) for pattern in patterns)


_PATTERNS: tuple[_TagPattern, ...] = (
    *_tags("Google Tag Manager", "tag_manager", r"\b(GTM-[A-Z0-9]{4,10})\b"),
    *_tags(
        "Google Analytics 4",
        "analytics",
        r"[?&]id=(G-[A-Z0-9]{6,12})\b",
        r"['\"](G-[A-Z0-9]{6,12})['\"]",
    ),
    *_tags("Universal Analytics", "analytics", r"\b(UA-\d{4,10}-\d{1,4})\b"),
    *_tags("Google Ads", "advertising", r"\b(AW-\d{6,12})\b"),
    *_tags(
        "Meta Pixel",
        "advertising",
        r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{8,20})['\"]",
        r"facebook\.com/tr/?\?id=(\d{8,20})",
        r"connect\.facebook\.net/[^'\"\s]*fbevents\.js",
    ),
    *_tags(
        "LinkedIn Insight",
        "advertising",
        r"_linkedin_partner_id\s*=\s*['\"]?(\d{4,12})",
        r"px\.ads\.linkedin\.com/collect/?\?pid=(\d{4,12})",
        r"snap\.licdn\.com/li\.lms-analytics",
    ),
    *_tags(
        "TikTok Pixel",
        "advertising",
        r"ttq\.load\(\s*['\"]([A-Z0-9]{15,25})['\"]",
        r"analytics\.tiktok\.com",
    ),
    *_tags(
        "Hotjar",
        "experience",
        r"\bhjid\s*:\s*(\d{4,10})",
        r"static\.hotjar\.com/c/hotjar-(\d{4,10})",
        r"static\.hotjar\.com",
    ),
    *_tags(
        "Microsoft Clarity",
        "experience",
        r"clarity\.ms/tag/([a-z0-9]{6,20})",
        r"['\"]clarity['\"]\s*,\s*['\"]script['\"]\s*,\s*['\"]([a-z0-9]{6,20})['\"]",
    ),
    *_tags("OneTrust", "consent", r"cdn\.cookielaw\.org|otSDKStub"),
    *_tags("Cookiebot", "consent", r"consent\.cookiebot\.com"),
    *_tags("CookieYes", "consent", r"cdn-cookieyes\.com"),
    *_tags("Usercentrics", "consent", r"usercentrics\.eu"),
    *_tags("Didomi", "consent", r"sdk\.privacy-center\.org"),
    *_tags("Osano", "consent", r"cmp\.osano\.com"),
    *_tags("Termly", "consent", r"app\.termly\.io"),
    *_tags("TrustArc", "consent", r"consent\.trustarc\.com"),
    *_tags("iubenda", "consent", r"cdn\.iubenda\.com"),
    *_tags("Quantcast Choice", "consent", r"cmp\.quantcast\.com"),
)


def find_tags(soup: Any) -> list[dict[str, Any]]:
    """Returns each tag found in script addresses, inline scripts, and `<noscript>` blocks."""
    return tags_in_sources(_sources(soup))


def tags_in_sources(
    sources: list[tuple[TagLocation, str]], known: Iterable[dict[str, Any]] = ()
) -> list[dict[str, Any]]:
    """Returns `known` tags plus each tag found in `sources`.

    A vendor found with an ID isn't listed again without one.
    """
    found = {(tag["vendor"], tag["id"]): tag for tag in known}
    for location, source in sources:
        for tag in _PATTERNS:
            for match in tag.pattern.finditer(source):
                tag_id = match.group(1) if tag.pattern.groups else None
                found.setdefault(
                    (tag.vendor, tag_id),
                    {
                        "vendor": tag.vendor,
                        "category": tag.category,
                        "id": tag_id,
                        "found_in": location,
                    },
                )
    with_ids = {vendor for vendor, tag_id in found if tag_id is not None}
    tags = [
        tag
        for (vendor, tag_id), tag in found.items()
        if tag_id is not None or vendor not in with_ids
    ]
    return tags[:_MAX_TAGS]


def _sources(soup: Any) -> list[tuple[TagLocation, str]]:
    sources: list[tuple[TagLocation, str]] = []
    for script in soup.find_all("script"):
        if src := script.get("src"):
            sources.append(("script_src", str(src)))
        elif text := script.get_text():
            sources.append(("inline_script", text[:_MAX_SCRIPT_SCAN_CHARS]))
    sources.extend(
        ("noscript", noscript.decode_contents()[:_MAX_SCRIPT_SCAN_CHARS])
        for noscript in soup.find_all("noscript")
    )
    return sources
