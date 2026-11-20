# apps/api/services/conversation_review/render_transcript.py

"""Render a stored conversation span as labelled plain text inside the untrusted frame."""

import json
from collections.abc import Sequence
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_core import to_jsonable_python

from services.agents.runtime.untrusted import (
    UntrustedContent,
    frame_untrusted_content,
    is_untrusted_content,
    untrusted_content_text,
)
from services.conversation_review.domain import (
    TOOL_ARGS_MAX_CHARS,
    TOOL_RESULT_MAX_CHARS,
    TRANSCRIPT_CLIPPED_NOTE,
    TRANSCRIPT_SOURCE_KIND,
)
from services.memories.recall_memories import recalled_ids_of
from utils.json_safe import json_safe_value


def render_transcript(messages: Sequence[ModelMessage], *, source_ref: str, max_chars: int) -> str:
    """Returns the framed transcript, keeping the newest `max_chars` characters.

    Thinking, system prompts, and retries are left out. Tool arguments and results are
    clipped, and values under credential-shaped keys are redacted. Approval payloads live
    in message metadata, which the stored span doesn't include.
    """
    blocks: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            blocks.extend(_request_blocks(message))
        elif isinstance(message, ModelResponse):
            blocks.extend(_response_blocks(message))
    text = "\n\n".join(blocks)
    if len(text) > max_chars:
        text = f"{TRANSCRIPT_CLIPPED_NOTE}\n\n{text[-max_chars:]}"
    return frame_untrusted_content(
        UntrustedContent(source_kind=TRANSCRIPT_SOURCE_KIND, source_ref=source_ref, content=text)
    )


def _request_blocks(message: ModelRequest) -> list[str]:
    blocks: list[str] = []
    for part in message.parts:
        if isinstance(part, UserPromptPart):
            blocks.append(f"[User]\n{_user_text(part.content)}")
        elif isinstance(part, ToolReturnPart):
            result = _clip(_tool_result_text(part.content), TOOL_RESULT_MAX_CHARS)
            blocks.append(f"[Tool result: {part.tool_name}]\n{result}")
    return blocks


def _response_blocks(message: ModelResponse) -> list[str]:
    blocks: list[str] = []
    for part in message.parts:
        if isinstance(part, TextPart) and part.content.strip():
            blocks.append(f"[Agent]\n{part.content}")
        elif isinstance(part, ToolCallPart):
            args = json.dumps(json_safe_value(part.args_as_dict()), ensure_ascii=False)
            blocks.append(f"[Agent called {part.tool_name}]\n{_clip(args, TOOL_ARGS_MAX_CHARS)}")
    return blocks


def _user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    # Recalled memories are already memories; learning from them again would echo them back.
    return "\n".join(
        item if isinstance(item, str) else "[attachment]"
        for item in content
        if not recalled_ids_of(item)
    )


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if is_untrusted_content(content):
        return untrusted_content_text(content)
    return json.dumps(
        json_safe_value(to_jsonable_python(content, fallback=str)), ensure_ascii=False
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}… [clipped]"
