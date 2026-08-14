# apps/api/services/ai_usage/domain.py

"""Closed AI usage purpose domain and validated event values."""

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

PURPOSE_AGENT_RUN = "agent_run"
PURPOSE_CONVERSATION_NAMING = "conversation_naming"
PURPOSE_HISTORY_SUMMARY = "history_summary"
PURPOSE_KB_ANNOTATION = "kb_annotation"
PURPOSE_CLASSIFICATION = "classification"
PURPOSE_WEB_SEARCH = "web_search"
PURPOSE_WEB_FETCH = "web_fetch"
PURPOSE_IMAGE_GENERATION = "image_generation"
PURPOSE_EMBEDDING_KB_INGEST = "embedding_kb_ingest"
PURPOSE_EMBEDDING_KB_SEARCH = "embedding_kb_search"
PURPOSE_EMBEDDING_MEMORY_WRITE = "embedding_memory_write"
PURPOSE_EMBEDDING_MEMORY_SEARCH = "embedding_memory_search"
PURPOSE_EMBEDDING_MEMORY_DEDUP = "embedding_memory_dedup"

AI_USAGE_PURPOSES = (
    PURPOSE_AGENT_RUN,
    PURPOSE_CONVERSATION_NAMING,
    PURPOSE_HISTORY_SUMMARY,
    PURPOSE_KB_ANNOTATION,
    PURPOSE_CLASSIFICATION,
    PURPOSE_WEB_SEARCH,
    PURPOSE_WEB_FETCH,
    PURPOSE_IMAGE_GENERATION,
    PURPOSE_EMBEDDING_KB_INGEST,
    PURPOSE_EMBEDDING_KB_SEARCH,
    PURPOSE_EMBEDDING_MEMORY_WRITE,
    PURPOSE_EMBEDDING_MEMORY_SEARCH,
    PURPOSE_EMBEDDING_MEMORY_DEDUP,
)

AI_USAGE_DETAILS_MAX_BYTES = 4096

type AIUsagePurpose = Literal[
    "agent_run",
    "conversation_naming",
    "history_summary",
    "kb_annotation",
    "classification",
    "web_search",
    "web_fetch",
    "image_generation",
    "embedding_kb_ingest",
    "embedding_kb_search",
    "embedding_memory_write",
    "embedding_memory_search",
    "embedding_memory_dedup",
]


@dataclass(frozen=True, slots=True)
class AIUsageEventData:
    """Validated inputs for one ledger row."""

    workspace_id: UUID
    provider: str
    model: str
    purpose: AIUsagePurpose
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    agent_id: UUID | None = None
    user_id: UUID | None = None
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.purpose not in AI_USAGE_PURPOSES:
            raise ValueError(f"Unknown AI usage purpose: {self.purpose!r}")
        if not self.provider.strip():
            raise ValueError("AI usage provider must not be empty")
        if not self.model.strip():
            raise ValueError("AI usage model must not be empty")
        for name in (
            "input_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "output_tokens",
            "requests",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"AI usage {name} must be a non-negative integer")
        if self.details is not None:
            try:
                encoded_details = json.dumps(
                    self.details,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            except (TypeError, ValueError) as exc:
                raise ValueError("AI usage details must be JSON serializable") from exc
            if len(encoded_details) > AI_USAGE_DETAILS_MAX_BYTES:
                raise ValueError("AI usage details exceed the 4096-byte serialized limit")

    @property
    def is_zero(self) -> bool:
        return not any(
            (
                self.input_tokens,
                self.cache_read_tokens,
                self.cache_write_tokens,
                self.output_tokens,
                self.requests,
            )
        )
