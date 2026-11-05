# apps/api/services/agents/runtime/progress_review/grant.py

"""Holds the extra steps that progress reviews grant to one run family."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from services.agents.runtime.progress_review.verdict import ProgressReview

PROGRESS_REVIEWS_KEY = "progress_reviews"
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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Set by the root run so a specialist's review is saved on the root run.
    persist: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)

    @classmethod
    def restore(cls, metadata: Mapping[str, Any] | None) -> "RequestGrant":
        saved = (metadata or {}).get(PROGRESS_REVIEWS_KEY)
        if saved is None:
            return cls()
        restored = SavedProgressReviews.model_validate(saved)
        return cls(granted=restored.granted, reviews=list(restored.reviews))

    @property
    def grants_used(self) -> int:
        return sum(1 for review in self.reviews if review.grants_steps)

    def record(self, review: ProgressReview, *, requests: int, steps: int) -> None:
        if review.grants_steps:
            self.granted += steps
        self.reviews.append(ProgressReviewEntry(**review.model_dump(), requests=requests))

    def snapshot(self) -> dict[str, Any]:
        return SavedProgressReviews(granted=self.granted, reviews=self.reviews).model_dump(
            mode="json"
        )

    def escalation_evidence(self) -> dict[str, Any] | None:
        """Describes the review that handed the run back to a person."""
        if not self.reviews or self.reviews[-1].grants_steps:
            return None
        return {
            "verdict": self.reviews[-1].verdict,
            "reason": self.reviews[-1].reason,
            "reviews_used": len(self.reviews),
        }
