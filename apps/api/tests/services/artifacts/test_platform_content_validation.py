# apps/api/tests/services/artifacts/test_platform_content_validation.py

import pytest

from core.exceptions.general import AppValidationError
from services.artifacts.platform.content_validation.utils import validate_platform_content


@pytest.mark.parametrize(
    ("artifact_type", "content"),
    [
        ("html", '<img src="/files/private.png">'),
        ("html", '<img src="&#47;files/private.png">'),
        ("html", '<img src="%252Ffiles%252Fprivate.png">'),
        ("html", '<img srcset="data:image/png;base64,YQ== 1x, /private.png 2x">'),
        ("html", '<iframe srcdoc="&lt;img src=/private.png&gt;"></iframe>'),
        ("html", '<meta http-equiv="refresh" content="0;url=/private">'),
        ("html", r'<script>fetch("\u002ffiles\u002fprivate")</script>'),
        ("html", r'<style>body{background:u\72l("/private.png")}</style>'),
        ("html", '<style>@im/**/port "https://example.com/private.css";</style>'),
        ("html", '<p style="background:url(https://example.com/private.png)">Text</p>'),
        ("markdown", "![Private](/files/private)"),
        ("markdown", "![Private][asset]\n\n[asset]: https://example.com/private.png"),
        ("markdown", "[Source](https://example.com/private-download)"),
        ("mermaid", 'flowchart LR\n A@{ img: "../private.png", label: "Private" }'),
    ],
)
def test_platform_content_rejects_dependencies(artifact_type: str, content: str) -> None:
    with pytest.raises(AppValidationError, match="must contain their assets") as caught:
        validate_platform_content(artifact_type=artifact_type, content=content)
    assert caught.value.field == "content"
    assert "private" not in caught.value.message


@pytest.mark.parametrize(
    ("artifact_type", "content"),
    [
        ("html", '<h1 id="report">Report</h1><a href="#report">Top</a>'),
        ("html", '<img src="data:image/png;base64,YQ==">'),
        ("html", "<style>body{color:red}svg{filter:url(#shadow)}</style>"),
        ("markdown", "![Chart](data:image/png;base64,YQ==)"),
        ("csv", "name,url\nExample,https://example.com/files/private"),
    ],
)
def test_platform_content_accepts_contained_assets(artifact_type: str, content: str) -> None:
    validate_platform_content(artifact_type=artifact_type, content=content)


def test_platform_content_rejects_repeated_unclosed_css_declarations() -> None:
    with pytest.raises(AppValidationError, match="must contain their assets"):
        validate_platform_content(artifact_type="html", content="<style>" + "url(" * 100_000)


@pytest.mark.parametrize(
    ("reference", "container"),
    [
        ("![Private][asset]", "> {reference}\n>\n> [asset]: {url}"),
        ("![asset][]", "- {reference}\n\n  [asset]: {url}"),
        ("[asset]", "- List\n  - {reference}\n\n    [asset]: {url}"),
    ],
)
def test_platform_markdown_rejects_nested_reference_destinations(
    reference: str, container: str
) -> None:
    content = container.format(reference=reference, url="https://example.com/private.png")
    with pytest.raises(AppValidationError, match="must contain their assets"):
        validate_platform_content(artifact_type="markdown", content=content)


@pytest.mark.parametrize(
    ("artifact_type", "content"),
    [
        ("html", '<img src="%23private.png">'),
        ("html", '<img src="&#37;23private.png">'),
        ("html", '<style>body{background:url("%23private.png")}</style>'),
        ("html", r'<style>body{background:url("\u0023private.png")}</style>'),
        ("markdown", "![Private](%23private.png)"),
    ],
)
def test_platform_content_checks_parsed_urls_before_additional_decoding(
    artifact_type: str, content: str
) -> None:
    with pytest.raises(AppValidationError, match="must contain their assets"):
        validate_platform_content(artifact_type=artifact_type, content=content)


@pytest.mark.parametrize(
    "content",
    [
        "<p>/*</p><style>body{background:url(private.png)}</style><p>*/</p>",
        "<style>body{color:red}</style><style>body{background:url(private.png)}</style>",
    ],
)
def test_platform_html_checks_each_style_element_independently(content: str) -> None:
    with pytest.raises(AppValidationError, match="must contain their assets"):
        validate_platform_content(artifact_type="html", content=content)


@pytest.mark.parametrize(
    ("artifact_type", "content"),
    [
        ("html", "<p>Check src/*.py for examples.</p>"),
        ("html", '<p>Use url(private.png) or @import "private.css" in CSS.</p>'),
        ("html", '<style>body{background:url("\\23 chart")}</style>'),
        ("markdown", '`![Chart](private.png)` and `<img src="private.png">`'),
        ("markdown", "> ![chart]\n>\n> [chart]: data:image/png;base64,YQ=="),
    ],
)
def test_platform_content_limits_dependency_parsing_to_rendered_contexts(
    artifact_type: str, content: str
) -> None:
    validate_platform_content(artifact_type=artifact_type, content=content)


def test_platform_markdown_rejects_nesting_beyond_the_parser_limit() -> None:
    prefix = "> " * 30
    content = f"{prefix}![asset]\n{prefix}\n{prefix}[asset]: https://example.com/private.png"
    with pytest.raises(AppValidationError, match="must contain their assets"):
        validate_platform_content(artifact_type="markdown", content=content)


@pytest.mark.parametrize(
    "content",
    [
        "| Preview |\n| --- |\n| ![asset] |\n\n[asset]: https://example.com/private.png",
        '> Inline HTML: <img src="https://example.com/private.png">',
    ],
)
def test_platform_markdown_validates_table_images_and_inline_html(content: str) -> None:
    with pytest.raises(AppValidationError, match="must contain their assets"):
        validate_platform_content(artifact_type="markdown", content=content)
