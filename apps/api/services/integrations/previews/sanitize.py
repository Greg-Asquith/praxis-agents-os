# apps/api/services/integrations/previews/sanitize.py

"""Server-side HTML sanitization for provider content previews.

The sanitized output is the only HTML the client ever receives; the client
adds a second layer (opaque-origin script-less iframe with a strict CSP).
Scripts, event handlers, forms, frames, and meta refresh never survive.
"""

import nh3

# Email HTML leans on legacy presentational markup; allow it while nh3's
# allowlist keeps every scripting and embedding vector out.
_EXTRA_TAGS = {"center", "font", "u", "html", "body", "head", "title", "span"}
_TAGS = set(nh3.ALLOWED_TAGS) | _EXTRA_TAGS

_GENERIC_ATTRIBUTES = {
    "style",
    "align",
    "valign",
    "width",
    "height",
    "bgcolor",
    "border",
    "cellpadding",
    "cellspacing",
    "color",
    "dir",
    "lang",
    "title",
}


def _attributes() -> dict[str, set[str]]:
    attributes: dict[str, set[str]] = {
        tag: set(values) for tag, values in nh3.ALLOWED_ATTRIBUTES.items()
    }
    attributes.setdefault("*", set()).update(_GENERIC_ATTRIBUTES)
    attributes.setdefault("a", set()).update({"href", "title"})
    attributes.setdefault("img", set()).update({"src", "alt", "width", "height"})
    attributes.setdefault("font", set()).update({"face", "size", "color"})
    attributes.setdefault("table", set()).update({"summary"})
    attributes.setdefault("td", set()).update({"colspan", "rowspan"})
    attributes.setdefault("th", set()).update({"colspan", "rowspan"})
    return attributes


_ATTRIBUTES = _attributes()

# data: stays allowed for inline images; anchors cannot navigate anywhere from
# the opaque-origin sandbox, so scheme risk is bounded by the client layer too.
_URL_SCHEMES = {"http", "https", "mailto", "tel", "data", "cid"}


def sanitize_preview_html(html: str) -> str:
    """Return provider HTML safe to hand to the browser preview layer."""
    return nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRIBUTES,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
