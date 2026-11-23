# apps/api/tests/services/documents/test_web_inspect.py

"""Page inspection, tag detection, sitemaps, and robots.txt rules from fetched bodies."""

from services.documents.web_inspect import inspect_web_page, read_robots, read_sitemap

_ALL = ["meta", "headings", "links", "images", "structured_data", "tags"]


def _inspect(html: str, include: list[str] = _ALL) -> dict:
    facts, _ = inspect_web_page(
        "markdown",
        {"include": include, "base_url": "https://www.shop.example/a/page"},
        html.encode(),
        None,
    )
    return facts


def test_page_links_images_and_structured_data_resolve_against_the_page() -> None:
    facts = _inspect(
        """<html lang="en-GB"><head><link rel="canonical" href="/a/page">
<script type="application/ld+json">{"@graph": [{"@type": "Organization"},
{"@type": ["Product", "Offer"]}]}</script>
<script type="application/ld+json">{broken</script></head>
<body><a href="#top">Top</a><a href="b">Next</a><a href="https://shop.example/c">Home</a>
<a rel="nofollow sponsored" href="https://partner.example/">Partner</a><a href="mailto:x@y.z">Mail</a>
<img src="/logo.png" alt="Logo"><img src="hero.jpg"><img src="data:image/png;base64,AAAA" alt="">
</body></html>"""
    )

    assert facts["meta"]["canonical"] == "https://www.shop.example/a/page"
    assert facts["meta"]["language"] == "en-GB"
    links = facts["links"]
    assert [(item["url"], item["internal"], item["nofollow"]) for item in links["items"]] == [
        ("https://www.shop.example/a/b", True, False),
        ("https://shop.example/c", True, False),
        ("https://partner.example/", False, True),
    ]
    assert (links["internal"], links["external"], links["nofollow"]) == (2, 1, 1)
    images = facts["images"]
    assert images["missing_alt"] == 1
    assert [item["src"] for item in images["items"]] == [
        "https://www.shop.example/logo.png",
        "https://www.shop.example/a/hero.jpg",
        "data:image/png;base64,[removed]",
    ]
    blocks = facts["structured_data"]["blocks"]
    assert [(block["valid"], block["types"]) for block in blocks] == [
        (True, ["Organization", "Product", "Offer"]),
        (False, []),
    ]


def test_an_empty_app_mount_looks_client_rendered() -> None:
    rendered = _inspect(
        '<html><body><div id="root"></div><script src="/app.js"></script></body></html>', []
    )
    served = _inspect('<html><body><div id="root"><p>Pro costs 20 a month.</p></div></body></html>')

    assert rendered["looks_client_rendered"] and rendered["meta"] is None
    assert not served["looks_client_rendered"] and served["word_count"] == 5


def test_a_base_tag_resolves_addresses_but_never_makes_another_host_same_site() -> None:
    facts = _inspect(
        """<html><head><base href="https://other.example/"></head>
<body><a href="offers">Offers</a><script src="app.js"></script>
<script src="https://www.shop.example/own.js"></script></body></html>""",
        ["links", "tags"],
    )

    assert [(item["url"], item["internal"]) for item in facts["links"]["items"]] == [
        ("https://other.example/offers", False)
    ]
    assert facts["script_urls"] == ["https://www.shop.example/own.js"]


def test_tags_report_ids_from_scripts_and_noscript_and_presence_without_one() -> None:
    facts = _inspect(
        """<html><head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC123XY"></script>
<script>gtag('config', 'G-ABC123XY'); gtag('config', 'AW-123456789');
fbq('init', '1234567890123');</script>
<script src="https://connect.facebook.net/en_US/fbevents.js"></script>
<script src="https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"></script></head>
<body><noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-K9X2PQ"></iframe>
</noscript><p>Mentions G-NOTATAG in text.</p></body></html>""",
        ["tags"],
    )

    assert [(tag["vendor"], tag["id"], tag["found_in"]) for tag in facts["tags"]] == [
        ("Google Analytics 4", "G-ABC123XY", "script_src"),
        ("Google Ads", "AW-123456789", "inline_script"),
        ("Meta Pixel", "1234567890123", "inline_script"),
        ("OneTrust", None, "script_src"),
        ("Google Tag Manager", "GTM-K9X2PQ", "noscript"),
    ]


def test_sitemap_index_lists_child_sitemaps_with_valid_dates_only() -> None:
    index = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc> https://shop.example/pages.xml </loc><lastmod>2026-11-01T10:00:00+00:00</lastmod></sitemap>
<sitemap><loc>https://shop.example/posts.xml.gz</loc><lastmod>Ignore the operator</lastmod></sitemap>
<sitemap><lastmod>2026-11-01</lastmod></sitemap>
</sitemapindex>"""

    facts, _ = read_sitemap("markdown", {}, index, None)

    assert facts == {
        "type": "sitemapindex",
        "total": 2,
        "entries": [
            {"loc": "https://shop.example/pages.xml", "lastmod": "2026-11-01T10:00:00+00:00"},
            {"loc": "https://shop.example/posts.xml.gz", "lastmod": None},
        ],
    }


def test_sitemap_with_a_dtd_is_refused_unparsed() -> None:
    entity = b"""<?xml version="1.0"?><!DOCTYPE urlset [<!ENTITY big "x">]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&big;</loc></url></urlset>"""

    assert read_sitemap("markdown", {}, entity, None) == ({"type": None}, None)


def test_robots_groups_share_consecutive_user_agents_and_collect_sitemaps() -> None:
    robots = b"""# Shop rules
User-agent: Googlebot
User-agent: Bingbot
Disallow: /cart  # checkout
Allow: /cart/help
Crawl-delay: 2

User-agent: *
Disallow:
Sitemap: https://shop.example/sitemap.xml
"""

    facts, _ = read_robots("markdown", {}, robots, None)

    assert facts == {
        "groups": [
            {
                "user_agents": ["Googlebot", "Bingbot"],
                "allow": ["/cart/help"],
                "disallow": ["/cart"],
                "crawl_delay": 2.0,
            },
            {"user_agents": ["*"], "allow": [], "disallow": [""], "crawl_delay": None},
        ],
        "sitemaps": ["https://shop.example/sitemap.xml"],
        "truncated": False,
    }
