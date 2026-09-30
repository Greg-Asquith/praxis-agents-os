# apps/api/services/documents/reading.py

"""Page budgets and untrusted-text framing for document reads.

Imported by the document worker process, so it uses the standard library only.
"""

import json
import math
from collections.abc import Iterable
from datetime import date, datetime, time
from typing import Any

MAX_NAME_CHARS = 100
DEFAULT_TABLE_ROWS = 200
MAX_TABLE_ROWS = 1_000
_POINTS_PER_EMU = 1 / 12_700
# Room for the keys, cursors, and File and revision fields around a page's items.
_ENVELOPE_CHARS = 1_000
_MAX_EXTERNAL_LINKS = 50


class DocumentRequestError(Exception):
    """The request names a sheet, range, or part the file doesn't have, or can't be paged."""


class ReadPage:
    """Collects one page of read output within a character budget.

    Text from the file is emitted in the runtime's untrusted-content node shape,
    so the budget measures what the model receives.
    """

    def __init__(self, args: dict[str, Any]) -> None:
        self.max_chars = max(int(args["max_chars"]) - _ENVELOPE_CHARS, 1)
        self.source_ref = str(args["source_ref"])
        self.used = 0
        self._repeated = 0

    def fits(self, item: Any, *, within: int | None = None) -> bool:
        """Counts an item if it fits. Use for metadata that only the first page carries.

        `within` caps the page's total use at a lower limit for this item.
        """
        size = _size(item)
        if self.used + size > min(self.max_chars, within or self.max_chars):
            return False
        self.used += size
        return True

    def reserve(self, item: Any, *, too_large: str) -> None:
        """Counts output that every page repeats, such as table columns."""
        size = _size(item)
        if self.used + size > self.max_chars:
            raise DocumentRequestError(too_large)
        self.used += size
        self._repeated += size

    def add(self, item: Any, *, first: bool, too_large: str) -> bool:
        """Counts a content item, or returns False so the page ends before it.

        The first item of a page is refused with `too_large` when no page could
        hold it. Otherwise it only waits for a page without first-page metadata.
        """
        size = _size(item)
        if self.used + size <= self.max_chars:
            self.used += size
            return True
        if first and size > self.max_chars - self._repeated:
            raise DocumentRequestError(too_large)
        return False

    def text(self, value: str) -> dict[str, str] | str:
        """Returns file text framed as untrusted content. Empty text stays a plain string."""
        if not value:
            return ""
        return {
            "node": "praxis_untrusted",
            "source_kind": "file",
            "source_ref": self.source_ref,
            "content": value,
        }

    def value(self, value: Any) -> Any:
        """Returns a cell value as JSON, framing strings and formatting dates."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, datetime | date | time):
            return value.isoformat()
        if isinstance(value, float) and not math.isfinite(value):
            return self.text(str(value))
        if isinstance(value, bool | int | float) or value is None:
            return value
        return self.text(str(value))


def name(value: Any) -> str:
    """Returns a file-supplied name or identifier, capped so it can't carry long text."""
    return str(value or "")[:MAX_NAME_CHARS]


def points(emu: int | None) -> float | None:
    """Converts English Metric Units to points."""
    return None if emu is None else round(emu * _POINTS_PER_EMU, 1)


def compact(values: dict[str, Any]) -> dict[str, Any]:
    """Drops keys whose value is None, False, or empty. Zero stays."""
    return {
        key: value
        for key, value in values.items()
        if value is not None and value is not False and value not in ("", [], {})
    }


def formatting(values: dict[str, Any]) -> dict[str, Any]:
    """Drops unset formatting but keeps explicit False, which overrides a style."""
    return {key: value for key, value in values.items() if value is not None and value != ""}


def color(color_format: Any) -> str | None:
    """Returns an RGB colour as `#RRGGBB`, or a theme colour as `theme:<name>`."""
    try:
        kind = color_format.type.name if color_format.type is not None else None
        if kind == "RGB" and color_format.rgb is not None:
            return f"#{color_format.rgb}"
        if kind in {"SCHEME", "THEME"}:
            return f"theme:{color_format.theme_color.name.lower()}"
    except (AttributeError, ValueError):
        return None
    return None


def spans(pieces: Iterable[tuple[str, dict[str, Any]]]) -> tuple[str, list[dict[str, Any]]]:
    """Joins text pieces and returns ranges of explicit formatting, merging equal neighbours."""
    texts: list[str] = []
    merged: list[dict[str, Any]] = []
    start = 0
    for text, style in pieces:
        end = start + len(text)
        if style and end > start:
            if merged and merged[-1]["end"] == start and merged[-1]["style"] == style:
                merged[-1]["end"] = end
            else:
                merged.append({"start": start, "end": end, "style": style})
        texts.append(text)
        start = end
    return "".join(texts), [
        {"start": span["start"], "end": span["end"], **span["style"]} for span in merged
    ]


def external_links(relationships: Iterable[tuple[str, str]], page: ReadPage) -> dict[str, Any]:
    """Lists external targets, such as hyperlinks and linked media, without fetching them."""
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for relationship_type, target in relationships:
        if (relationship_type, target) in seen:
            continue
        seen.add((relationship_type, target))
        item = {"kind": name(relationship_type.rsplit("/", 1)[-1]), "target": page.text(target)}
        if len(links) >= _MAX_EXTERNAL_LINKS or not page.fits(item):
            return {"external_links": links, "external_links_truncated": True}
        links.append(item)
    return compact({"external_links": links})


def _size(item: Any) -> int:
    # One more for the comma that separates the item from the next.
    return len(json.dumps(item, ensure_ascii=False, separators=(",", ":"))) + 1
