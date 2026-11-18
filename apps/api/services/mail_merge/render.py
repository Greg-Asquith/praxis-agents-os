# apps/api/services/mail_merge/render.py

"""Fill a merge template for one recipient, with no model involved."""

import hashlib
import html
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from core.exceptions.general import AppValidationError
from services.integrations.previews.sanitize import sanitize_preview_html

# RFC 5322 caps a header line at 998 characters.
MAX_SUBJECT_CHARS = 998

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|([^{}]*))?\}\}")


@dataclass(frozen=True)
class MergeTemplate:
    """A checked template: every placeholder names a known column, and the body is sanitised."""

    subject: str
    body_html: str
    fallbacks: Mapping[str, str]


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    body_html: str


@dataclass(frozen=True)
class RenderResult:
    """The filled email, or why this row can't be sent as it is."""

    email: RenderedEmail | None
    problems: tuple[str, ...] = ()


def parse_merge_template(
    *,
    subject: str,
    body_html: str,
    fallbacks: Mapping[str, str],
    columns: Collection[str],
) -> MergeTemplate:
    """Checks the template against the recipient columns and sanitises the body once.

    Raises:
        AppValidationError: Thrown when a placeholder is malformed or names an unknown
            column, a fallback names an unknown column, or the subject has a line break.
    """
    if _has_line_break(subject):
        raise AppValidationError("The subject can't contain a line break.", field="subject")
    if any(_has_line_break(value) for value in fallbacks.values()):
        raise AppValidationError("A fallback can't contain a line break.", field="fallbacks")
    unknown_fallbacks = sorted(set(fallbacks) - set(columns))
    if unknown_fallbacks:
        raise AppValidationError(
            f"Fallbacks name columns the recipients don't have: {', '.join(unknown_fallbacks)}.",
            field="fallbacks",
        )
    clean_body = sanitize_preview_html(body_html)
    for field, text in (("subject", subject), ("body_html", clean_body)):
        _check_placeholders(text, columns=columns, field=field)
    return MergeTemplate(subject=subject, body_html=clean_body, fallbacks=dict(fallbacks))


def render_merge_email(template: MergeTemplate, values: Mapping[str, Any]) -> RenderResult:
    """Returns the template filled from one recipient's values.

    The same template and values always give the same bytes. A row with a missing value and
    no fallback, or a subject value with a line break, isn't rendered.
    """
    problems: list[str] = []
    subject = _fill(template.subject, template, values, problems, escape=False)
    body = _fill(template.body_html, template, values, problems, escape=True)
    if len(subject) > MAX_SUBJECT_CHARS:
        problems.append(f"The subject would be longer than {MAX_SUBJECT_CHARS} characters.")
    if problems:
        return RenderResult(email=None, problems=tuple(dict.fromkeys(problems)))
    # Values are escaped text, but one placed in an attribute could still form a link.
    return RenderResult(email=RenderedEmail(subject=subject, body_html=sanitize_preview_html(body)))


def content_fingerprint(*, subject: str, body_html: str, fallbacks: Mapping[str, str]) -> str:
    """Returns a hash of what an approval's test send covers, so an edit after it shows."""
    payload = json.dumps(
        {"subject": subject, "body_html": body_html, "fallbacks": dict(fallbacks)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _check_placeholders(text: str, *, columns: Collection[str], field: str) -> None:
    unknown = sorted({match.group(1) for match in _PLACEHOLDER.finditer(text)} - set(columns))
    if unknown:
        names = ", ".join("{{" + name + "}}" for name in unknown)
        raise AppValidationError(
            f"{names} doesn't match a recipient column.",
            field=field,
            details={"unknown_placeholders": unknown},
        )
    leftover = _PLACEHOLDER.sub("", text)
    if "{{" in leftover or "}}" in leftover:
        raise AppValidationError(
            "Write placeholders as {{column}} or {{column|fallback}}.", field=field
        )


def _has_line_break(text: str) -> bool:
    return "\r" in text or "\n" in text


def _fill(
    text: str,
    template: MergeTemplate,
    values: Mapping[str, Any],
    problems: list[str],
    *,
    escape: bool,
) -> str:
    def replace(match: re.Match[str]) -> str:
        name, inline_fallback = match.group(1), match.group(2)
        raw = values.get(name)
        value = "" if raw is None else str(raw).strip()
        if value and not escape and _has_line_break(value):
            problems.append(f"The {name} would put a line break in the subject.")
            return ""
        if value:
            return html.escape(value) if escape else value
        # An inline fallback is template text, already sanitised with the body.
        if inline_fallback is not None and inline_fallback.strip():
            return inline_fallback.strip()
        fallback = (template.fallbacks.get(name) or "").strip()
        if fallback:
            return html.escape(fallback) if escape else fallback
        problems.append(f"No {name}, and no fallback for it.")
        return ""

    return _PLACEHOLDER.sub(replace, text)
