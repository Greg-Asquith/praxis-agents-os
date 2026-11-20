# apps/api/services/memories/dream/domain.py

"""Dream run lifecycle, the typed operations a dream may return, and apply inputs.

"Dream" is an internal name. The product calls this learning from past conversations.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.memories.domain import MemoryScope, MemoryType

DREAM_STATUS_COLLECTING = "collecting"
DREAM_STATUS_EXTRACTING = "extracting"
DREAM_STATUS_CONSOLIDATING = "consolidating"
DREAM_STATUS_APPLYING = "applying"
DREAM_STATUS_COMPLETED = "completed"
DREAM_STATUS_FAILED = "failed"

FINAL_DREAM_STATUSES = frozenset({DREAM_STATUS_COMPLETED, DREAM_STATUS_FAILED})

# A run with nothing to read or nothing to change completes early.
ALLOWED_DREAM_TRANSITIONS: dict[str, frozenset[str]] = {
    DREAM_STATUS_COLLECTING: frozenset(
        {DREAM_STATUS_EXTRACTING, DREAM_STATUS_COMPLETED, DREAM_STATUS_FAILED}
    ),
    DREAM_STATUS_EXTRACTING: frozenset({DREAM_STATUS_CONSOLIDATING, DREAM_STATUS_FAILED}),
    DREAM_STATUS_CONSOLIDATING: frozenset(
        {DREAM_STATUS_APPLYING, DREAM_STATUS_COMPLETED, DREAM_STATUS_FAILED}
    ),
    DREAM_STATUS_APPLYING: frozenset({DREAM_STATUS_COMPLETED, DREAM_STATUS_FAILED}),
    DREAM_STATUS_COMPLETED: frozenset(),
    DREAM_STATUS_FAILED: frozenset(),
}

DREAM_AUDIT_ACTOR = "memory.dream"
MEMORY_DREAM_JOB_KIND = "memory.dream"
MEMORY_DREAM_SCHEDULE_JOB_KIND = "memory.dream_schedule"
DREAM_RUN_SUBJECT_TYPE = "memory_dream_run"

# Why a run failed.
DREAM_ERROR_JOB_FAILED = "job_failed"
DREAM_ERROR_STALLED = "stalled"
DREAM_ERROR_DISABLED = "disabled"
DREAM_ERROR_BATCH_DEADLINE = "batch_deadline"
DREAM_ERROR_BATCH_FAILED = "batch_failed"

MAX_CANDIDATES_PER_CONVERSATION = 10
# The scope's most important memories, shown to extraction so it doesn't repeat them.
KNOWN_MEMORIES_PER_SCOPE = 20
NEAREST_MEMORIES_PER_CANDIDATE = 3
# Below the dedup floor: pairs above it were already refused when written.
DUPLICATE_CLUSTER_SIMILARITY = 0.85
DUPLICATE_CLUSTER_RECENT_MEMORIES = 300
MAX_DUPLICATE_PAIRS = 10
EXTRACTION_CONCURRENCY = 4

# Batch checks back off from the first to the max; both stay under the shortest interval,
# so a waiting run keeps moving and the scheduler never takes it for stalled.
BATCH_FIRST_CHECK = timedelta(minutes=2)
BATCH_MAX_CHECK_INTERVAL = timedelta(minutes=30)
# OpenAI and Anthropic end a batch within 24 hours; one still open after this is cancelled.
BATCH_DEADLINE = timedelta(hours=25)

# Why a valid operation changed nothing.
SKIP_PROTECTED = "protected"
SKIP_STALE = "stale"
SKIP_INVALID_CONTENT = "invalid_content"
SKIP_EMBEDDING_UNAVAILABLE = "embedding_unavailable"
SKIP_REMOVED_BY_PERSON = "removed_by_person"
SKIP_NEAR_DUPLICATE = "near_duplicate"
SKIP_OVER_LIMIT = "over_limit"

# Why a whole response changed nothing.
REJECT_UNKNOWN_REFERENCE = "unknown_reference"
REJECT_REPEATED_REFERENCE = "repeated_reference"
REJECT_SCOPE_MISMATCH = "scope_mismatch"


def can_transition_dream_run(current: str, target: str) -> bool:
    """Checks whether a dream run may move from current to target status."""
    return target in ALLOWED_DREAM_TRANSITIONS.get(current, frozenset())


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DreamCreate(_Operation):
    """Save a new note. `conversation` names the conversation it was learned from."""

    op: Literal["create"]
    title: str
    content_md: str
    memory_type: MemoryType
    importance: int = Field(default=3, ge=1, le=5)
    conversation: str | None = None


class DreamRevise(_Operation):
    """Replace one memory with corrected content."""

    op: Literal["revise"]
    memory: str
    content_md: str
    title: str | None = None
    conversation: str | None = None


class DreamMerge(_Operation):
    """Replace two or more memories with one."""

    op: Literal["merge"]
    memories: list[str] = Field(min_length=2)
    title: str
    content_md: str


class DreamRetire(_Operation):
    """Archive a memory that has gone stale."""

    op: Literal["retire"]
    memory: str


class DreamReinforce(_Operation):
    """Record that a later conversation confirmed a memory."""

    op: Literal["reinforce"]
    memory: str


type DreamOperation = Annotated[
    DreamCreate | DreamRevise | DreamMerge | DreamRetire | DreamReinforce,
    Field(discriminator="op"),
]


class DreamCandidate(BaseModel):
    """Something one conversation showed is worth remembering."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="A short label for the memory.")
    content_md: str = Field(description="The current understanding, as one or two sentences.")
    memory_type: MemoryType
    importance: int = Field(default=3, ge=1, le=5)
    evidence: str = Field(description="A short quote from the conversation that supports it.")
    corrects: str | None = Field(
        default=None,
        description="What earlier understanding this replaces, when the conversation corrected one.",
    )


class DreamExtraction(BaseModel):
    """Extraction output for one conversation. An empty list is the usual answer."""

    model_config = ConfigDict(extra="forbid")

    memories: list[DreamCandidate]


class DreamConsolidation(BaseModel):
    """Consolidation output for one scope. An empty list changes nothing."""

    model_config = ConfigDict(extra="forbid")

    operations: list[DreamOperation]


class DreamStepError(Exception):
    """Every model call in a step failed, so the job retries instead of moving on."""


@dataclass(frozen=True)
class DreamScopeTarget:
    """The one scope a request may write, chosen by the server.

    `agent` and `user` fill the scope's references; at workspace scope they only
    attribute embedding usage.
    """

    workspace: Workspace
    scope: MemoryScope
    agent: Agent
    user: User

    @property
    def key(self) -> str:
        """Names the scope uniquely within one run."""
        if self.scope == "agent":
            return f"agent:{self.agent.id}"
        if self.scope == "user":
            return f"user:{self.user.id}"
        return f"workspace:{self.workspace.id}"


@dataclass(frozen=True)
class DreamScopeRequest:
    """What the server showed the model for one scope, by the references it used."""

    target: DreamScopeTarget
    memories: Mapping[str, UUID]
    conversations: Mapping[str, UUID] = field(default_factory=dict)


@dataclass
class DreamApplyResult:
    """What one apply changed, skipped, or refused."""

    applied: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    rejected: str | None = None
    already_applied: bool = False
