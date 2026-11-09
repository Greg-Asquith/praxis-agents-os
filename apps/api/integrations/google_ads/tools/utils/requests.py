# apps/api/integrations/google_ads/tools/utils/requests.py

"""Checks a tool's whole request, so the agent gets the rule it broke as a plain retry."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_ai import ModelRetry


def validated_request[T: BaseModel](model: type[T], values: Mapping[str, Any]) -> T:
    """Validates a request across its fields.

    Raises:
        ModelRetry: With the first rule the request breaks.
    """
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        error = exc.errors(include_url=False, include_input=False)[0]
        message = str(error["ctx"]["error"]) if error["type"] == "value_error" else error["msg"]
        raise ModelRetry(message) from None
