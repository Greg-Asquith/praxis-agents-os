# apps/api/services/conversation_summaries/domain.py 

"""Conversation history-summary contracts shared by runtime and jobs."""

from pydantic import BaseModel, Field

SUMMARIZE_HISTORY_JOB_KIND = "conversations.summarize_history"


class HistorySummaryOutput(BaseModel):
    """Structured output from the history-summary utility model."""

    summary: str = Field(description="A compact factual summary of the earlier conversation.")
