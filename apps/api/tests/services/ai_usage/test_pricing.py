"""Public model-price registry contracts."""

from datetime import date
from decimal import Decimal

from services.agents.models.registry import list_models
from services.ai_usage.pricing import find_image_output_price, find_price
from services.embeddings.registry import list_embedding_models


def test_effective_date_lookup_selects_latest_applicable_price() -> None:
    introductory = find_price("anthropic", "claude-sonnet-5", date(2026, 8, 31))
    standard = find_price("anthropic", "claude-sonnet-5", date(2026, 9, 1))

    assert introductory is not None
    assert introductory.input_usd_per_mtok == 2
    assert standard is not None
    assert standard.input_usd_per_mtok == 3


def test_unknown_or_not_yet_effective_model_is_unpriced() -> None:
    assert find_price("azure", "customer-deployment", date(2026, 8, 12)) is None
    assert find_price("openai", "gpt-5.6-sol", date(2026, 7, 8)) is None


def test_every_live_catalog_model_has_current_pricing() -> None:
    on_date = date(2026, 8, 12)
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


def test_gemini_flash_image_uses_standard_1k_output_price() -> None:
    price = find_image_output_price(
        "google",
        "gemini-3.1-flash-image",
        "standard",
        "1k",
        date(2026, 8, 12),
    )

    assert price is not None
    assert price.usd_per_image == Decimal("0.067")
