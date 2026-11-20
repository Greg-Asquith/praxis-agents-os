# apps/api/services/conversation_review/domain.py

"""What a background review reads from one finished conversation."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

TRANSCRIPT_SOURCE_KIND = "conversation_transcript"
TOOL_ARGS_MAX_CHARS = 500
TOOL_RESULT_MAX_CHARS = 1_500
TRANSCRIPT_CLIPPED_NOTE = "[Earlier messages left out]"


@dataclass(frozen=True)
class FinishedConversation:
    """A conversation with a completed run in the review window.

    `end_sequence` is one past the last stored message, so a later read of
    `[start, end_sequence)` rebuilds the same transcript.
    """

    id: UUID
    user_id: UUID
    agent_id: UUID
    visibility: str
    first_finished_at: datetime
    end_sequence: int
