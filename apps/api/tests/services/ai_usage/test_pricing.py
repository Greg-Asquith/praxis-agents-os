"""Public model-price registry contracts."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

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


def test_openai_price_cuts_are_effective_from_july_30() -> None:
    terra_before = find_price("openai", "gpt-5.6-terra", date(2026, 7, 29))
    terra_after = find_price("openai", "gpt-5.6-terra", date(2026, 7, 30))
    luna_before = find_price("openai", "gpt-5.6-luna", date(2026, 7, 29))
    luna_after = find_price("openai", "gpt-5.6-luna", date(2026, 7, 30))

    assert terra_before is not None
    assert terra_before.input_usd_per_mtok == Decimal("2.5")
    assert terra_after is not None
    assert (
        terra_after.input_usd_per_mtok,
        terra_after.cache_read_usd_per_mtok,
        terra_after.cache_write_usd_per_mtok,
        terra_after.output_usd_per_mtok,
    ) == (Decimal("2"), Decimal("0.2"), Decimal("2.5"), Decimal("12"))
    assert luna_before is not None
    assert luna_before.input_usd_per_mtok == Decimal("1")
    assert luna_after is not None
    assert (
        luna_after.input_usd_per_mtok,
        luna_after.cache_read_usd_per_mtok,
        luna_after.cache_write_usd_per_mtok,
        luna_after.output_usd_per_mtok,
    ) == (Decimal("0.2"), Decimal("0.02"), Decimal("0.25"), Decimal("1.2"))


@pytest.mark.parametrize(
    ("model", "release_date"),
    [("gemini-3.8-flash", date(2026, 9, 2)), ("gemini-3.7-flash", date(2026, 8, 13))],
)
def test_gemini_flash_introductory_pricing_expires_in_2027(model: str, release_date: date) -> None:
    before_release = find_price("google", model, release_date - timedelta(days=1))
    introductory = find_price("google", model, release_date)
    standard = find_price("google", model, date(2027, 1, 1))

    assert before_release is None
    assert introductory is not None
    assert (
        introductory.input_usd_per_mtok,
        introductory.cache_read_usd_per_mtok,
        introductory.cache_write_usd_per_mtok,
        introductory.output_usd_per_mtok,
    ) == (Decimal("0.75"), Decimal("0.075"), Decimal("0.75"), Decimal("3.75"))
    assert standard is not None
    assert (
        standard.input_usd_per_mtok,
        standard.cache_read_usd_per_mtok,
        standard.cache_write_usd_per_mtok,
        standard.output_usd_per_mtok,
    ) == (Decimal("1.5"), Decimal("0.15"), Decimal("1.5"), Decimal("7.5"))


def test_fable_5_1_cache_reads_are_a_quarter_of_fable_5() -> None:
    before_release = find_price("anthropic", "claude-fable-5-1", date(2026, 8, 31))
    fable_5_1 = find_price("anthropic", "claude-fable-5-1", date(2026, 9, 1))
    fable_5 = find_price("anthropic", "claude-fable-5", date(2026, 9, 1))

    assert before_release is None
    assert fable_5_1 is not None
    assert fable_5 is not None
    assert (
        fable_5_1.input_usd_per_mtok,
        fable_5_1.cache_read_usd_per_mtok,
        fable_5_1.cache_write_usd_per_mtok,
        fable_5_1.output_usd_per_mtok,
    ) == (Decimal("10"), Decimal("0.25"), Decimal("12.5"), Decimal("50"))
    assert fable_5.cache_read_usd_per_mtok == Decimal("1")


def test_unknown_or_not_yet_effective_model_is_unpriced() -> None:
    assert find_price("azure", "customer-deployment", date(2026, 8, 12)) is None
    assert find_price("openai", "gpt-5.6-sol", date(2026, 7, 8)) is None


def test_every_live_catalog_model_has_current_pricing() -> None:
    on_date = date(2026, 9, 5)
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


@pytest.mark.parametrize("variant", ["reasoning", "non-reasoning"])
def test_grok_vertex_pricing_uses_catalog_alias_and_input_cache_fallback(variant):
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
