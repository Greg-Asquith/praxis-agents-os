"""Public model-price registry contracts."""

from datetime import date
from decimal import Decimal

from services.agents.models.registry import list_models
from services.ai_usage.get_model_pricing import get_model_pricing
from services.ai_usage.pricing import find_image_output_price, find_price
from services.embeddings.registry import list_embedding_models


def test_pricing_catalogue_returns_one_effective_rate_per_model() -> None:
    catalogue = get_model_pricing(date(2026, 9, 10))
    keys = [(price.provider, price.model) for price in catalogue.models]
    assert keys == sorted(set(keys))
    assert all(price.effective_from <= catalogue.as_of for price in catalogue.models)
    payload = catalogue.model_dump(mode="json")
    assert payload["as_of"] == "2026-09-10"
    assert isinstance(payload["models"][0]["input_usd_per_mtok"], str)


def test_effective_date_lookup_selects_latest_applicable_price() -> None:
    launch = find_price("openai", "gpt-5.6-luna", date(2026, 7, 29))
    reduced = find_price("openai", "gpt-5.6-luna", date(2026, 7, 30))

    assert launch is not None
    assert launch.input_usd_per_mtok == 1
    assert reduced is not None
    assert reduced.input_usd_per_mtok == Decimal("0.2")


def test_unknown_or_not_yet_effective_model_is_unpriced() -> None:
    assert find_price("azure", "customer-deployment", date(2026, 8, 12)) is None
    assert find_price("openai", "gpt-5.6-sol", date(2026, 7, 8)) is None


def test_every_live_catalog_model_has_current_pricing() -> None:
    on_date = date(2026, 9, 29)
    missing = [
        model.qualified_id
        for model in list_models()
        if find_price(model.provider, model.model, on_date) is None
    ]
    missing.extend(
        model.qualified_id
        for model in list_embedding_models()
        if find_price(model.provider, model.model, on_date) is None
    )

    assert missing == []


def test_vertex_pricing_uses_input_rate_as_cache_fallback() -> None:
    variant = "reasoning"
    price = find_price("xai", f"grok-4-20-{variant}", date(2026, 9, 5))
    assert price is not None
    assert price.input_usd_per_mtok == Decimal("1.25")
    assert price.cache_read_usd_per_mtok == price.input_usd_per_mtok
    assert price.cache_write_usd_per_mtok == price.input_usd_per_mtok
    assert price.output_usd_per_mtok == Decimal("2.50")
    assert find_price("xai", f"grok-4-20-{variant}", date(2026, 9, 4)) is None


def test_gpt_image_output_pricing_uses_returned_quality_and_size() -> None:
    price = find_image_output_price(
        "openai",
        "gpt-image-2",
        "medium",
        "1024x1024",
        date(2026, 8, 12),
    )

    assert price is not None
    assert price.usd_per_image == Decimal("0.053")
    assert (
        find_image_output_price(
            "openai",
            "gpt-image-2",
            "auto",
            "1024x1024",
            date(2026, 8, 12),
        )
        is None
    )
