"""Meta creative specs: every automatic change explicit, and each format mapped as Meta expects."""

from integrations.meta_ads.creative_features import AUTOMATIC_CHANGES
from integrations.meta_ads.operations.creatives import (
    EMPTY_DESCRIPTION,
    CreativeCard,
    CreativeImage,
    CreativeInput,
    CreativeVideo,
    conversion_domain,
    creative_spec,
)


def creative(**overrides) -> CreativeInput:
    values = {
        "format": "image",
        "page_id": "11",
        "instagram_user_id": "22",
        "primary_text": "Spring sale",
        "headline": "20% off",
        "description": None,
        "link": "https://shop.example.com/sale",
        "call_to_action": "SHOP_NOW",
        "url_tags": "utm_source=meta",
        "media": CreativeImage("abc"),
        "vertical": None,
        "cards": (),
        "enabled": frozenset(),
    }
    return CreativeInput(**{**values, **overrides})


def test_an_all_off_image_sends_every_change_off_and_an_enabled_one_on():
    spec = creative_spec(creative())

    features = spec["degrees_of_freedom_spec"]["creative_features_spec"]
    assert set(features) == {change.feature for change in AUTOMATIC_CHANGES if change.feature}
    assert {detail["enroll_status"] for detail in features.values()} == {"OPT_OUT"}
    assert spec["contextual_multi_ads"] == {"enroll_status": "OPT_OUT"}
    assert spec["destination_spec"] == {"destination_type": "WEBSITE_AND_SHOP_OPT_OUT"}
    assert spec["interactive_components_spec"]["components"][0]["enroll_status"] == "opt_out"
    assert spec["asset_feed_spec"] == {"audios": [{"type": "OPTED_OUT"}]}
    # Related media holds only the media we list, so leaving it out adds none.
    assert "media_sourcing_spec" not in spec
    assert {item["data_source"][0] for item in spec["format_transformation_spec"]} == {"none"}
    link_data = spec["object_story_spec"]["link_data"]
    # Headline, description, and button are always sent, so Meta fills in none of them.
    assert link_data["name"] == "20% off"
    assert link_data["description"] == EMPTY_DESCRIPTION
    assert link_data["call_to_action"] == {
        "type": "SHOP_NOW",
        "value": {"link": "https://shop.example.com/sale"},
    }
    assert spec["url_tags"] == "utm_source=meta"

    enabled = creative_spec(creative(enabled=frozenset({"image_touchups", "music"})))
    features = enabled["degrees_of_freedom_spec"]["creative_features_spec"]
    assert features["image_touchups"] == {"enroll_status": "OPT_IN"}
    assert features["inline_comment"] == {"enroll_status": "OPT_OUT"}
    assert enabled["asset_feed_spec"] == {"audios": [{"type": "RANDOM"}]}


def test_a_video_uses_the_chosen_thumbnail_and_has_no_image_only_values():
    spec = creative_spec(
        creative(format="video", media=CreativeVideo("55", thumbnail_hash="thumb"))
    )

    video_data = spec["object_story_spec"]["video_data"]
    assert (video_data["video_id"], video_data["image_hash"]) == ("55", "thumb")
    assert video_data["title"] == "20% off"
    assert "interactive_components_spec" not in spec
    assert "asset_feed_spec" not in spec


def test_a_carousel_keeps_its_card_order_and_turns_meta_reordering_off():
    cards = (
        CreativeCard(CreativeImage("one"), "First", None, "https://example.com/a", "SHOP_NOW"),
        CreativeCard(
            CreativeVideo("77", thumbnail_url="https://scontent.fbcdn.net/t.jpg"),
            "Second",
            "Details",
            "https://example.com/b",
            "LEARN_MORE",
        ),
    )
    spec = creative_spec(creative(format="carousel", media=None, headline=None, cards=cards))

    link_data = spec["object_story_spec"]["link_data"]
    first, second = link_data["child_attachments"]
    assert (first["image_hash"], first["name"], first["description"]) == (
        "one",
        "First",
        EMPTY_DESCRIPTION,
    )
    assert (second["video_id"], second["picture"]) == ("77", "https://scontent.fbcdn.net/t.jpg")
    assert link_data["multi_share_optimized"] is False
    assert link_data["multi_share_end_card"] is False
    assert spec["portrait_customizations"] == {"carousel_delivery_mode": "fixed_num_cards"}


def test_a_vertical_version_shows_only_in_stories_and_reels():
    spec = creative_spec(creative(vertical=CreativeImage("tall")))

    assert "link_data" not in spec["object_story_spec"]
    feed = spec["asset_feed_spec"]
    assert feed["optimization_type"] == "PLACEMENT"
    assert feed["images"] == [
        {"hash": "abc", "adlabels": [{"name": "main"}]},
        {"hash": "tall", "adlabels": [{"name": "vertical"}]},
    ]
    vertical, main = feed["asset_customization_rules"]
    assert vertical["image_label"] == {"name": "vertical"} and vertical["priority"] == 1
    assert vertical["customization_spec"]["instagram_positions"] == ["story", "reels"]
    assert main["image_label"] == {"name": "main"} and main["priority"] == 2
    # Music stays explicit in the same feed.
    assert feed["audios"] == [{"type": "OPTED_OUT"}]
    assert feed["bodies"][0]["automation_status"] == "OPT_OUT"


def test_conversion_domain_keeps_the_registrable_domain():
    assert conversion_domain("https://shop.example.com/sale") == "example.com"
    assert conversion_domain("https://www.example.co.uk/") == "example.co.uk"
