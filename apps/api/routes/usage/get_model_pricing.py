# apps/api/routes/usage/get_model_pricing.py

"""Route for the model token pricing catalogue."""

from datetime import UTC, datetime

from fastapi import APIRouter

from services.ai_usage.get_model_pricing import get_model_pricing
from services.ai_usage.schemas import ModelPricingResponse

router = APIRouter()


@router.get("/model-pricing")
async def read_model_pricing() -> ModelPricingResponse:
    return get_model_pricing(datetime.now(UTC).date())
