# apps/api/services/ai_usage/pricing.py

"""Effective-dated public API prices for metered models."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model: str
    effective_from: date
    input_usd_per_mtok: Decimal
    cache_read_usd_per_mtok: Decimal
    cache_write_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal


@dataclass(frozen=True)
class ImageOutputPrice:
    provider: str
    model: str
    effective_from: date
    quality: str
    size: str
    usd_per_image: Decimal


def _price(
    provider: str,
    model: str,
    effective_from: date,
    input_rate: str,
    cache_read_rate: str,
    cache_write_rate: str,
    output_rate: str,
) -> ModelPrice:
    return ModelPrice(
        provider=provider,
        model=model,
        effective_from=effective_from,
        input_usd_per_mtok=Decimal(input_rate),
        cache_read_usd_per_mtok=Decimal(cache_read_rate),
        cache_write_usd_per_mtok=Decimal(cache_write_rate),
        output_usd_per_mtok=Decimal(output_rate),
    )


# Standard OpenAI API rates as of 2026-08-13.
# https://developers.openai.com/api/docs/models
_OPENAI_PRICES = (
    _price("openai", "gpt-5.6-sol", date(2026, 7, 9), "5", "0.5", "6.25", "30"),
    _price("openai", "gpt-5.6-terra", date(2026, 7, 9), "2.5", "0.25", "3.125", "15"),
    _price("openai", "gpt-5.6-terra", date(2026, 7, 30), "2", "0.2", "2.5", "12"),
    _price("openai", "gpt-5.6-luna", date(2026, 7, 9), "1", "0.1", "1.25", "6"),
    _price("openai", "gpt-5.6-luna", date(2026, 7, 30), "0.2", "0.02", "0.25", "1.2"),
    _price("openai", "gpt-5.5", date(2026, 4, 23), "5", "0.5", "5", "30"),
    _price("openai", "gpt-5.4", date(2026, 3, 5), "2.5", "0.25", "2.5", "15"),
    _price("openai", "gpt-5.4-mini", date(2026, 3, 17), "0.75", "0.075", "0.75", "4.5"),
    _price("openai", "gpt-5.4-nano", date(2026, 3, 17), "0.2", "0.02", "0.2", "1.25"),
    _price("openai", "text-embedding-3-small", date(2024, 1, 25), "0.02", "0", "0", "0"),
    _price("openai", "text-embedding-3-large", date(2024, 1, 25), "0.13", "0", "0", "0"),
)

# Standard first-party Claude API rates as of 2026-08-12. Cache writes use
# the default five-minute rate; one-hour writes and regional inference are not
# distinguishable in the usage ledger.
# https://platform.claude.com/docs/en/about-claude/pricing
_ANTHROPIC_PRICES = (
    _price("anthropic", "claude-fable-5", date(2026, 6, 9), "10", "1", "12.5", "50"),
    _price("anthropic", "claude-opus-4-8", date(2026, 5, 27), "5", "0.5", "6.25", "25"),
    _price("anthropic", "claude-opus-4-7", date(2026, 5, 27), "5", "0.5", "6.25", "25"),
    _price("anthropic", "claude-opus-4-6", date(2026, 5, 27), "5", "0.5", "6.25", "25"),
    _price("anthropic", "claude-sonnet-5", date(2026, 6, 30), "2", "0.2", "2.5", "10"),
    _price("anthropic", "claude-sonnet-5", date(2026, 9, 1), "3", "0.3", "3.75", "15"),
    _price("anthropic", "claude-sonnet-4-6", date(2026, 5, 27), "3", "0.3", "3.75", "15"),
    _price("anthropic", "claude-haiku-4-5", date(2026, 5, 27), "1", "0.1", "1.25", "5"),
)

# Standard Gemini Developer API rates as of 2026-08-12. Context-cache storage
# duration and non-standard execution tiers are outside the ledger contract.
# https://ai.google.dev/gemini-api/docs/pricing
_GOOGLE_PRICES = (
    _price("google", "gemini-3.6-flash", date(2026, 8, 12), "1.5", "0.15", "1.5", "7.5"),
    _price("google", "gemini-3.5-flash", date(2026, 7, 21), "1.5", "0.15", "1.5", "9"),
    _price("google", "gemini-3.5-flash-lite", date(2026, 8, 12), "0.3", "0.03", "0.3", "2.5"),
    _price("google", "gemini-3.1-pro", date(2026, 8, 12), "2", "0.2", "2", "12"),
    _price("google", "gemini-3.1-flash-lite", date(2026, 8, 12), "0.25", "0.025", "0.25", "1.5"),
    _price("google", "gemini-embedding-2", date(2026, 4, 22), "0.2", "0", "0", "0"),
)

# Local Ollama inference has no provider API token charge. Operator-owned
# hardware and electricity are intentionally outside this token-price estimate.
# https://www.ollama.com/pricing (local models are unlimited on local hardware)
_OLLAMA_PRICES = (_price("ollama", "bge-m3", date(2024, 1, 1), "0", "0", "0", "0"),)

MODEL_PRICES: tuple[ModelPrice, ...] = (
    *_OPENAI_PRICES,
    *_ANTHROPIC_PRICES,
    *_GOOGLE_PRICES,
    *_OLLAMA_PRICES,
)

# Image-output estimates as of 2026-08-12. Text and source-image input costs are
# not included where the helper does not expose their image-model usage
# separately from its mainline model usage.
# https://developers.openai.com/api/docs/guides/image-generation#calculating-costs
_OPENAI_IMAGE_OUTPUT_PRICES = tuple(
    ImageOutputPrice("openai", "gpt-image-2", date(2026, 4, 21), quality, size, Decimal(cost))
    for quality, costs in {
        "low": {"1024x1024": "0.006", "1024x1536": "0.005", "1536x1024": "0.005"},
        "medium": {"1024x1024": "0.053", "1024x1536": "0.041", "1536x1024": "0.041"},
        "high": {"1024x1024": "0.211", "1024x1536": "0.165", "1536x1024": "0.165"},
    }.items()
    for size, cost in costs.items()
)

# Gemini 3.1 Flash Image standard-tier output pricing. The native helper does
# not expose a resolution selector and Google documents 1K as the default.
# https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-image
_GOOGLE_IMAGE_OUTPUT_PRICES = (
    ImageOutputPrice(
        "google",
        "gemini-3.1-flash-image",
        date(2026, 2, 26),
        "standard",
        "1k",
        Decimal("0.067"),
    ),
)

IMAGE_OUTPUT_PRICES: tuple[ImageOutputPrice, ...] = (
    *_OPENAI_IMAGE_OUTPUT_PRICES,
    *_GOOGLE_IMAGE_OUTPUT_PRICES,
)


def find_price(provider: str, model: str, on_date: date) -> ModelPrice | None:
    """Return the latest price effective on a UTC usage date."""
    applicable = (
        price
        for price in MODEL_PRICES
        if price.provider == provider and price.model == model and price.effective_from <= on_date
    )
    return max(applicable, key=lambda price: price.effective_from, default=None)


def find_image_output_price(
    provider: str,
    model: str,
    quality: str,
    size: str,
    on_date: date,
) -> ImageOutputPrice | None:
    """Return the latest exact image-output estimate for known output metadata."""
    applicable = (
        price
        for price in IMAGE_OUTPUT_PRICES
        if price.provider == provider
        and price.model == model
        and price.quality == quality
        and price.size == size
        and price.effective_from <= on_date
    )
    return max(applicable, key=lambda price: price.effective_from, default=None)
