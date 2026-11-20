# apps/api/services/memories/dream/batch.py

"""Send a dream step's model requests as one provider batch, through Pydantic AI only.

The run stores the batch handle and who each request is for, never a transcript.
Decoding a result needs only the request's settings and output parameters, so it is
rebuilt from the output type.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError
from pydantic_ai import Agent as HelperAgent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.batch import Batch, BatchRequest, BatchResult
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from services.memories.dream.domain import (
    BATCH_FIRST_CHECK,
    BATCH_MAX_CHECK_INTERVAL,
)

logger = logging.getLogger(__name__)

_BATCH = TypeAdapter(Batch)


class _RequestCapturedError(Exception):
    def __init__(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        parameters: ModelRequestParameters,
    ) -> None:
        super().__init__("captured")
        self.messages = messages
        self.model_settings = model_settings
        self.parameters = parameters


class _CaptureModel(WrapperModel):
    """Stops a helper agent at its first model request and hands the request back."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise _RequestCapturedError(messages, model_settings, model_request_parameters)


def uses_batch(model: Model) -> bool:
    """Pydantic AI's batch support for the model picks the transport; no setting does."""
    return model.batch_max_requests is not None


async def build_batch_request[T](
    model: Model,
    *,
    custom_id: str,
    output_type: type[T],
    instructions: str | None,
    prompt: str,
) -> BatchRequest:
    """Returns the request the direct helper agent would send, without sending it."""
    helper = HelperAgent(
        _CaptureModel(model),
        name="memory_dream",
        output_type=output_type,
        instructions=instructions,
    )
    try:
        await helper.run(prompt)
    except _RequestCapturedError as captured:
        return BatchRequest(
            custom_id=custom_id,
            messages=captured.messages,
            model_settings=captured.model_settings,
            model_request_parameters=captured.parameters,
        )
    raise RuntimeError("The dream helper made no model request")


async def submit_batch(
    model: Model, requests: Sequence[BatchRequest], *, now: datetime
) -> dict[str, Any]:
    """Submits the requests as one batch and returns what the run stores to collect it."""
    encoded = [await model.batch_encode(request) for request in requests]
    batch = await model.batch_create(encoded)
    return {
        "batch": _BATCH.dump_python(batch, mode="json"),
        "submitted_at": now.isoformat(),
        "checks": 0,
    }


def stored_batch(stored: Mapping[str, Any]) -> Batch:
    return _BATCH.validate_python(stored["batch"])


def next_batch_check(stored: Mapping[str, Any], *, now: datetime) -> datetime:
    """Checks back sooner at first, then at most every BATCH_MAX_CHECK_INTERVAL."""
    return now + min(BATCH_FIRST_CHECK * 2 ** stored["checks"], BATCH_MAX_CHECK_INTERVAL)


def parse_output[T](response: ModelResponse, request: BatchRequest, output_type: type[T]) -> T:
    """Validates a decoded response as the helper agent would, from its output tool or text.

    Raises ValidationError or ValueError when the response holds no valid output.
    """
    output_tools = {tool.name for tool in request.model_request_parameters.output_tools}
    adapter = TypeAdapter(output_type)
    for part in response.parts:
        if isinstance(part, ToolCallPart) and part.tool_name in output_tools:
            return adapter.validate_python(part.args_as_dict())
    if response.text is None:
        raise ValueError("The response holds no output")
    return adapter.validate_json(response.text)


def decode_output[T](
    model: Model, result: BatchResult, request: BatchRequest, output_type: type[T]
) -> tuple[ModelResponse | None, T | None]:
    """Returns the decoded response, for usage, and its output; either is None when unusable."""
    try:
        response = model.batch_decode(result, replace(request, custom_id=result.custom_id))
    except Exception:
        logger.warning(
            "Dream batch request failed; it changes nothing",
            exc_info=True,
            extra={"custom_id": result.custom_id, "status": result.status},
        )
        return None, None
    try:
        return response, parse_output(response, request, output_type)
    except (ValidationError, ValueError):
        logger.warning(
            "Dream batch response was invalid; it changes nothing",
            extra={"custom_id": result.custom_id, "output": output_type.__name__},
        )
        return response, None
