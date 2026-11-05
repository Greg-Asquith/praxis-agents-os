# apps/api/services/agents/runtime/progress_review/review.py

"""Asks the configured reviewer whether a run should carry on past its step limit."""

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.progress_review.verdict import ProgressReview, ask_person


async def review_progress(ctx: RunContext[RuntimeDeps]) -> ProgressReview:
    """Hands every run back to a person until reviewer models are wired in."""
    return ask_person("Automatic progress reviews are not available yet.")
