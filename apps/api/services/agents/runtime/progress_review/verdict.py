# apps/api/services/agents/runtime/progress_review/verdict.py

"""The verdict contract shared by every progress reviewer."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal[
    "continue", "steer_wrap_up", "steer_stop_repeating", "steer_refocus", "ask_person"
]
REASON_MAX_CHARS = 500

# Praxis writes every steer instruction so reviewer output never becomes agent instructions.
STEER_TEXT: dict[Verdict, str] = {
    "steer_wrap_up": (
        "Progress check: you are close to done. Finish the remaining work and give your final "
        "answer in the next few steps."
    ),
    "steer_stop_repeating": (
        "Progress check: your recent steps repeat the same actions without new results. Try a "
        "different approach, or explain what is blocking you and finish."
    ),
    "steer_refocus": (
        "Progress check: your recent steps have drifted from the original task. Return to the "
        "task as given and finish it."
    ),
}


class ProgressReview(BaseModel):
    """One reviewer decision at the step limit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    reason: Annotated[str, Field(max_length=REASON_MAX_CHARS)] = ""
    provider: Annotated[str, Field(max_length=64)] | None = None
    model: Annotated[str, Field(max_length=128)] | None = None

    @property
    def grants_steps(self) -> bool:
        return self.verdict != "ask_person"


def ask_person(reason: str) -> ProgressReview:
    return ProgressReview(verdict="ask_person", reason=reason[:REASON_MAX_CHARS])
