# apps/api/services/agents/runtime/progress_review/grant.py

"""Holds the extra steps that progress reviews grant to one run family."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import RunContext

from core.settings import settings
from services.agents.runtime.progress_review.verdict import ProgressReview

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps

PROGRESS_REVIEWS_KEY = "progress_reviews"
GRANTS_USED_REASON = "The run used every automatic extension it is allowed."
MAX_PROGRESS_REVIEW_GRANTS = 10
Count = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class ProgressReviewEntry(ProgressReview):
    """One review as saved in run metadata."""

    requests: Count


class SavedProgressReviews(BaseModel):
    """Validates the bounded, server-owned review history of one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    granted: Count = 0
    # Every grant plus the one review that asks a person and ends the run.
    reviews: Annotated[
        list[ProgressReviewEntry], Field(max_length=MAX_PROGRESS_REVIEW_GRANTS + 1)
    ] = []


@dataclass
class RequestGrant:
    """Live request allowance shared by a root run and its specialists."""

    granted: int = 0
    reviews: list[ProgressReviewEntry] = field(default_factory=list)
    # The root agent's setting; when off, the step limit always pauses for a person.
    enabled: bool = True
    max_grants: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Set by the root run so a specialist's review is saved on the root run. Returns the
    # transcript row for the review, given the reviewed run, requests granted, and steer text.
    persist: Callable[["RuntimeDeps", int, str | None], Awaitable[UUID]] | None = field(
        default=None, repr=False
    )
    # The root run's latest context, so a specialist's review can describe the delegating run.
    root_context: RunContext[Any] | None = field(default=None, repr=False)

    @classmethod
    def restore(cls, metadata: Mapping[str, Any] | None, *, enabled: bool) -> "RequestGrant":
        """Restores saved grants, which stay in force even when reviews are later turned off."""
        max_grants = settings.AGENT_RUN_PROGRESS_REVIEW_MAX_GRANTS
        grant = cls(enabled=enabled and max_grants > 0, max_grants=max_grants)
        saved = (metadata or {}).get(PROGRESS_REVIEWS_KEY)
        if saved is not None:
            restored = SavedProgressReviews.model_validate(saved)
            grant.granted, grant.reviews = restored.granted, list(restored.reviews)
        return grant

    @property
    def grants_used(self) -> int:
        return sum(1 for review in self.reviews if review.grants_steps)

    @property
    def limit_reached(self) -> bool:
        return self.enabled and self.grants_used >= self.max_grants

    def record(self, review: ProgressReview, *, requests: int, steps: int) -> int:
        """Adds the review and returns the requests it granted."""
        granted = steps if review.grants_steps else 0
        self.granted += granted
        self.reviews.append(ProgressReviewEntry(**review.model_dump(), requests=requests))
        return granted

    def snapshot(self) -> dict[str, Any]:
        return SavedProgressReviews(granted=self.granted, reviews=self.reviews).model_dump(
            mode="json"
        )

    def escalation_evidence(self) -> dict[str, Any] | None:
        """Describes why the step limit handed the run back to a person after reviews."""
        latest = self.reviews[-1] if self.reviews else None
        if latest is not None and not latest.grants_steps:
            reason, limit_reached = latest.reason, False
        elif self.limit_reached:
            reason, limit_reached = GRANTS_USED_REASON, True
        else:
            return None
        return {
            "verdict": "ask_person",
            "reason": reason,
            "reviews_used": len(self.reviews),
            "limit_reached": limit_reached,
        }
