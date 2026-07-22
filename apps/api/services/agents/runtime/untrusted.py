# apps/api/services/agents/runtime/untrusted.py

"""Shared framing for attacker-influenced model-visible content."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


def frame_untrusted_content(value: Any) -> Any:
    """Recursively replace untrusted carriers with model-visible frames."""
    transformed, _changed = _transform(value)
    return transformed


def _transform(value: Any) -> tuple[Any, bool]:
    if isinstance(value, UntrustedContent):
        return _render_frame(value), True
    if isinstance(value, Mapping):
        changed = False
        transformed = {}
        for key, item in value.items():
            transformed_item, item_changed = _transform(item)
            transformed[key] = transformed_item
            changed = changed or item_changed
        return (transformed, True) if changed else (value, False)
    if isinstance(value, list):
        transformed_items = []
        changed = False
        for item in value:
            transformed_item, item_changed = _transform(item)
            transformed_items.append(transformed_item)
            changed = changed or item_changed
        return (transformed_items, True) if changed else (value, False)
    if isinstance(value, tuple):
        transformed_items = []
        changed = False
        for item in value:
            transformed_item, item_changed = _transform(item)
            transformed_items.append(transformed_item)
            changed = changed or item_changed
        return (tuple(transformed_items), True) if changed else (value, False)
    return value, False


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
