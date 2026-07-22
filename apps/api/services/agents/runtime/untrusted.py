# apps/api/services/agents/runtime/untrusted.py

"""Structured provenance and model-only framing for untrusted content."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

UNTRUSTED_CONTENT_START = "<<<PRAXIS_UNTRUSTED_CONTENT>>>"
UNTRUSTED_CONTENT_END = "<<<END_PRAXIS_UNTRUSTED_CONTENT>>>"
_NEUTRALIZED_START = "<<<PRAXIS_UNTRUSTED-CONTENT>>>"
_NEUTRALIZED_END = "<<<END_PRAXIS_UNTRUSTED-CONTENT>>>"
_SOURCE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9._:/-]+")
_SOURCE_COMPONENT_MAX_LENGTH = 160


@dataclass(frozen=True)
class UntrustedContent:
    """Runtime-internal carrier for content plus server-minted provenance."""

    source_kind: str
    source_ref: str
    content: str


class UntrustedNode(BaseModel):
    """Serializable untrusted content plus server-minted provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node: Literal["praxis_untrusted"] = "praxis_untrusted"
    source_kind: str
    source_ref: str
    content: str

    @field_validator("source_kind")
    @classmethod
    def sanitize_source_kind(cls, value: str) -> str:
        return _sanitize_source_component(value, fallback="external")

    @field_validator("source_ref")
    @classmethod
    def sanitize_source_ref(cls, value: str) -> str:
        return _sanitize_source_component(value, fallback="unknown")


type UntrustedJsonValue = (
    str
    | int
    | float
    | bool
    | None
    | UntrustedNode
    | list["UntrustedJsonValue"]
    | dict[str, "UntrustedJsonValue"]
)
type NodeReplacement = Callable[[UntrustedNode], Any]


def serialize_untrusted_content(value: Any) -> Any:
    """Recursively replace runtime-only carriers with serializable nodes."""
    transformed, _changed = _transform(value, replacement=_keep_node)
    return transformed


def render_untrusted_frames(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Render structured nodes only in the history sent to a model."""
    transformed_messages: list[ModelMessage] = []
    changed = False
    for message in messages:
        if not isinstance(message, ModelRequest):
            transformed_messages.append(message)
            continue

        transformed_parts = []
        message_changed = False
        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                transformed_parts.append(part)
                continue
            content, content_changed = _transform(part.content, replacement=_render_node)
            transformed_parts.append(replace(part, content=content) if content_changed else part)
            message_changed = message_changed or content_changed

        transformed_messages.append(
            replace(message, parts=transformed_parts) if message_changed else message
        )
        changed = changed or message_changed
    return transformed_messages if changed else messages


def frame_untrusted_content(value: Any) -> Any:
    """Render carriers directly for legacy callers outside persisted history."""
    transformed, _changed = _transform(value, replacement=_render_node)
    return transformed


def _transform(value: Any, *, replacement: NodeReplacement) -> tuple[Any, bool]:
    if isinstance(value, UntrustedContent):
        return replacement(_node_from_carrier(value)), True
    node = _node_from_value(value)
    if node is not None:
        return replacement(node), True
    if isinstance(value, Mapping):
        changed = False
        transformed = {}
        for key, item in value.items():
            transformed_item, item_changed = _transform(item, replacement=replacement)
            transformed[key] = transformed_item
            changed = changed or item_changed
        return (transformed, True) if changed else (value, False)
    if isinstance(value, list):
        transformed_items = []
        changed = False
        for item in value:
            transformed_item, item_changed = _transform(item, replacement=replacement)
            transformed_items.append(transformed_item)
            changed = changed or item_changed
        return (transformed_items, True) if changed else (value, False)
    if isinstance(value, tuple):
        transformed_items = []
        changed = False
        for item in value:
            transformed_item, item_changed = _transform(item, replacement=replacement)
            transformed_items.append(transformed_item)
            changed = changed or item_changed
        return (tuple(transformed_items), True) if changed else (value, False)
    return value, False


def _node_from_carrier(value: UntrustedContent) -> UntrustedNode:
    return UntrustedNode(
        source_kind=value.source_kind,
        source_ref=value.source_ref,
        content=value.content,
    )


def _keep_node(value: UntrustedNode) -> UntrustedNode:
    return value


def _node_from_value(value: Any) -> UntrustedNode | None:
    if isinstance(value, UntrustedNode):
        return value
    if not isinstance(value, Mapping) or value.get("node") != "praxis_untrusted":
        return None
    try:
        return UntrustedNode.model_validate(value)
    except ValueError:
        return None


def _render_node(value: UntrustedNode) -> str:
    return _render_frame(
        UntrustedContent(
            source_kind=value.source_kind,
            source_ref=value.source_ref,
            content=value.content,
        )
    )


def _render_frame(value: UntrustedContent) -> str:
    source_kind = _sanitize_source_component(value.source_kind, fallback="external")
    source_ref = _sanitize_source_component(value.source_ref, fallback="unknown")
    content = value.content.replace(UNTRUSTED_CONTENT_START, _NEUTRALIZED_START).replace(
        UNTRUSTED_CONTENT_END,
        _NEUTRALIZED_END,
    )
    return (
        f'{UNTRUSTED_CONTENT_START} source_kind="{source_kind}" '
        f'source_ref="{source_ref}">>>\n{content}\n{UNTRUSTED_CONTENT_END}'
    )


def _sanitize_source_component(value: str, *, fallback: str) -> str:
    normalized = _SOURCE_COMPONENT_PATTERN.sub("_", value.strip())
    normalized = normalized.strip("._")[:_SOURCE_COMPONENT_MAX_LENGTH]
    return normalized or fallback
