# apps/api/services/agents/runtime/history.py

"""Trim model history at stable user-turn watermarks."""

from collections.abc import Callable, Sequence

from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolReturnPart,
    UserPromptPart,
)

from core.settings import settings


def trim_history(
    messages: list[ModelMessage],
    *,
    max_turns: int,
    keep_turns: int,
) -> list[ModelMessage]:
    """Return a provider-valid chunked trim of prior message history."""
    if keep_turns >= max_turns:
        raise ValueError("keep_turns must be less than max_turns")

    prior_messages, current_run_messages = _split_current_run_tail(messages)
    boundary_indexes = [
        index for index, message in enumerate(prior_messages) if _is_clean_user_boundary(message)
    ]
    if len(boundary_indexes) <= max_turns:
        return messages

    watermark_size = max_turns - keep_turns
    dropped_boundaries = ((len(boundary_indexes) - keep_turns) // watermark_size) * watermark_size
    cut_index = boundary_indexes[dropped_boundaries]
    dropped = prior_messages[:cut_index]
    kept = list(prior_messages[cut_index:])
    capability_pairs = _capability_load_pairs(
        dropped,
        loaded_capability_ids=_loaded_capability_ids(kept),
    )
    if not capability_pairs:
        return [*kept, *current_run_messages]

    synthetic_call_response = ModelResponse(parts=[call for call, _return in capability_pairs])
    synthetic_return_request = ModelRequest(
        parts=[return_part for _call, return_part in capability_pairs]
    )
    return [
        kept[0],
        synthetic_call_response,
        synthetic_return_request,
        *kept[1:],
        *current_run_messages,
    ]


def history_trimmer() -> Callable[[list[ModelMessage]], list[ModelMessage]]:
    """Return a ProcessHistory-compatible callable using live settings."""

    def process(messages: list[ModelMessage]) -> list[ModelMessage]:
        max_turns = settings.AGENT_HISTORY_MAX_TURNS
        if max_turns is None:
            return messages
        return trim_history(
            messages,
            max_turns=max_turns,
            keep_turns=settings.AGENT_HISTORY_KEEP_TURNS,
        )

    return process


def _is_clean_user_boundary(message: ModelMessage) -> bool:
    if not isinstance(message, ModelRequest):
        return False
    has_user_prompt = False
    for part in message.parts:
        if isinstance(part, UserPromptPart):
            has_user_prompt = True
        elif isinstance(part, ToolReturnPart | RetryPromptPart):
            return False
    return has_user_prompt


def _split_current_run_tail(
    messages: list[ModelMessage],
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    if not messages:
        return messages, []
    current_run_id = messages[-1].run_id
    if current_run_id is None:
        return messages, []
    for index, message in enumerate(messages):
        if message.run_id == current_run_id:
            return messages[:index], messages[index:]
    return messages, []


def _loaded_capability_ids(messages: Sequence[ModelMessage]) -> set[str]:
    return {
        capability_id for capability_id, _call, _return in _iter_capability_load_pairs(messages)
    }


def _capability_load_pairs(
    messages: Sequence[ModelMessage],
    *,
    loaded_capability_ids: set[str],
) -> list[tuple[LoadCapabilityCallPart, LoadCapabilityReturnPart]]:
    pairs: list[tuple[LoadCapabilityCallPart, LoadCapabilityReturnPart]] = []
    preserved_capability_ids: set[str] = set()
    for capability_id, call, return_part in _iter_capability_load_pairs(messages):
        if capability_id in loaded_capability_ids or capability_id in preserved_capability_ids:
            continue
        preserved_capability_ids.add(capability_id)
        pairs.append((call, return_part))
    return pairs


def _iter_capability_load_pairs(
    messages: Sequence[ModelMessage],
) -> list[tuple[str, LoadCapabilityCallPart, LoadCapabilityReturnPart]]:
    calls_by_id: dict[str, LoadCapabilityCallPart] = {}
    capability_by_call_id: dict[str, str] = {}
    pairs: list[tuple[str, LoadCapabilityCallPart, LoadCapabilityReturnPart]] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, LoadCapabilityCallPart):
                capability_id = part.capability_id
                if capability_id is None:
                    continue
                calls_by_id[part.tool_call_id] = part
                capability_by_call_id[part.tool_call_id] = capability_id
            elif isinstance(part, LoadCapabilityReturnPart):
                capability_id = capability_by_call_id.get(part.tool_call_id)
                call = calls_by_id.get(part.tool_call_id)
                if capability_id is None or call is None:
                    continue
                pairs.append((capability_id, call, part))
    return pairs
