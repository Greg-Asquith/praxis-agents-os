# apps/api/tests/services/mail_merge/test_render.py

"""Filling a merge template: placeholders, fallbacks, escaping, and subject headers."""

import pytest

from core.exceptions.general import AppValidationError
from services.mail_merge import render_merge_email
from services.mail_merge.render import parse_merge_template

COLUMNS = ("email", "first_name", "last_name", "company")


def _template(subject: str = "Hello {{first_name}}", body: str = "<p>Hi</p>", **fallbacks: str):
    return parse_merge_template(
        subject=subject, body_html=body, fallbacks=fallbacks, columns=COLUMNS
    )


def test_unknown_or_malformed_placeholder_rejects_the_whole_template() -> None:
    with pytest.raises(AppValidationError) as unknown:
        _template(body="<p>Hi {{firstname}}</p>")
    assert unknown.value.details == {"unknown_placeholders": ["firstname"]}

    with pytest.raises(AppValidationError):
        _template(body="<p>Hi {{first name}}</p>")


def test_missing_value_uses_inline_then_argument_fallback_and_otherwise_is_not_rendered() -> None:
    template = _template(
        subject="Hello {{first_name|there}}",
        body="<p>{{company}} and {{last_name}}</p>",
        company="your team",
    )

    filled = render_merge_email(template, {"first_name": " ", "company": None, "last_name": "Lee"})
    assert filled.email is not None
    assert filled.email.subject == "Hello there"
    assert filled.email.body_html == "<p>your team and Lee</p>"

    missing = render_merge_email(template, {"first_name": "Dana", "company": "Example"})
    assert missing.email is None
    assert missing.problems == ("No last_name, and no fallback for it.",)


def test_field_values_are_escaped_in_the_body_and_cannot_form_a_script_link() -> None:
    template = _template(body='<p>Hi {{first_name}}</p><a href="{{company}}">Site</a>')

    filled = render_merge_email(
        template,
        {"first_name": "<script>alert(1)</script>", "company": "javascript:alert(1)"},
    )

    assert filled.email is not None
    assert "<script>" not in filled.email.body_html
    assert "&lt;script&gt;" in filled.email.body_html
    assert "javascript:" not in filled.email.body_html


def test_line_break_in_a_subject_value_marks_the_row_instead_of_adding_a_header() -> None:
    result = render_merge_email(_template(), {"first_name": "Dana\r\nBcc: kai@example.com"})

    assert result.email is None
    assert result.problems == ("The first_name would put a line break in the subject.",)
