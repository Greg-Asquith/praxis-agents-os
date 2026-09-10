# apps/api/services/ai_usage/get_model_pricing.py

"""Read the token rates used for usage estimates on a UTC date."""

from datetime import date

from services.ai_usage.pricing import MODEL_PRICES, find_price
from services.ai_usage.schemas import ModelPricingResponse


def get_model_pricing(on_date: date) -> ModelPricingResponse:
    models = sorted({(price.provider, price.model) for price in MODEL_PRICES})
    return ModelPricingResponse(
        as_of=on_date,
        models=[
            price
            for provider, model in models
            if (price := find_price(provider, model, on_date)) is not None
        ],
    )
