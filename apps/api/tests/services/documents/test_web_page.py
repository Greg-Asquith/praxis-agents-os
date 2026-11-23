# apps/api/tests/services/documents/test_web_page.py

"""Part and drop selection and page facts for fetched HTML pages."""

from services.documents.web_page import page_facts, web_page

_PAGE = b"""<html><head><title>Shop</title><style>p{}</style></head>
<body style="margin:0"><nav><a href="/about">About</a></nav>
<main><h1>Pricing</h1><img alt="Chart" src="data:image/png;base64,AAAA"><!-- note -->
<script>gtag('config', 'G-ABC123')</script></main></body></html>"""


def _render(**args: object) -> tuple[dict[str, object], str]:
    value, payload = web_page("markdown", {"drop": [], "max_bytes": 100_000, **args}, _PAGE, None)
    return value, (payload or b"").decode()


def test_part_and_drop_select_what_a_page_returns() -> None:
    _, main = _render(format="markdown", part="main")
    _, body = _render(format="markdown", part="body")
    _, default_html = _render(
        format="html", part="full", drop=["styles", "svg", "comments", "data_uris"]
    )
    value, served = _render(format="html", part="full")

    assert value["title"] == "Shop"
    assert "# Pricing" in main and "About" not in main and "gtag" not in main
    assert "[About](/about)" in body
    assert "G-ABC123" in default_html and "<style>" not in default_html
    assert "data:image/png;base64,[removed]" in default_html
    assert "note" not in default_html and 'style="margin:0"' not in default_html
    assert "<!-- note -->" in served and "AAAA" in served


def test_page_facts_read_meta_tags_case_insensitively() -> None:
    page = b"""<html><head><title> Shop </title><meta name="Description" content="Plans">
<meta name="robots" content="noindex"><link rel="alternate canonical" href="https://shop.example/">
</head><body><h1>One</h1><h1>Two</h1></body></html>"""

    facts, payload = page_facts("markdown", {}, page, None)

    assert payload is None
    assert facts == {
        "title": "Shop",
        "description": "Plans",
        "canonical": "https://shop.example/",
        "robots": "noindex",
        "h1_count": 2,
    }
