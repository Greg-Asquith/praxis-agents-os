# apps/api/integrations/notion/tools/search_cursor.py

"""Opaque, workspace-scoped continuations for Notion search fan-out."""

import base64
import binascii
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai import ModelRetry

from ..operations.utils import MAX_NOTION_PROVIDER_CURSOR_CHARS

MAX_SCOPED_CURSOR_CHARS = 16_384


class _SearchCursorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    workspace_id: str = Field(min_length=1, max_length=512)
    provider_cursor: str = Field(min_length=1, max_length=MAX_NOTION_PROVIDER_CURSOR_CHARS)


def encode_search_cursor(*, workspace_id: str, provider_cursor: str) -> str:
    """Encode one provider cursor with the workspace scope that issued it."""
    try:
        payload = _SearchCursorPayload(
            workspace_id=workspace_id,
            provider_cursor=provider_cursor,
        )
        serialized = payload.model_dump_json().encode()
        encoded = base64.urlsafe_b64encode(serialized).decode().rstrip("=")
        if len(encoded) > MAX_SCOPED_CURSOR_CHARS:
            raise ValueError
    except (ValueError, ValidationError):
        raise ModelRetry(
            "The Notion search continuation is invalid. Start the search again."
        ) from None
    return encoded


def decode_search_cursor(value: str) -> tuple[str, str]:
    """Decode a scoped cursor or ask the model to restart the search."""
    try:
        if not value or len(value) > MAX_SCOPED_CURSOR_CHARS:
            raise ValueError
        padding = "=" * (-len(value) % 4)
        serialized = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        payload = _SearchCursorPayload.model_validate(json.loads(serialized))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error, ValidationError):
        raise ModelRetry(
            "The Notion search continuation is invalid. Start the search again."
        ) from None
    return payload.workspace_id, payload.provider_cursor
