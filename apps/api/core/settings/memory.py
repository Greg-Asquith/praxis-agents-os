# apps/api/core/settings/memory.py

"""Agent-memory settings."""

from pydantic import Field


class MemorySettingsMixin:
    """Validated limits and lifecycle defaults for agent memories."""

    MEMORY_DEDUP_SIMILARITY: float = Field(
        default=0.92,
        gt=0,
        lt=1,
        description="Cosine-similarity floor for near-duplicate resolution.",
    )
    MEMORY_EMBED_WRITE_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        gt=0,
        description="Synchronous embedding budget for one memory write.",
    )
    MEMORY_DECAY_RATE_FACT: float = Field(
        default=0.005,
        gt=0,
        description="Provisional fact decay; tune only with Gate G4 eval evidence.",
    )
    MEMORY_DECAY_RATE_PREFERENCE: float = Field(
        default=0.002,
        gt=0,
        description="Provisional preference decay; tune only with Gate G4 eval evidence.",
    )
    MEMORY_DECAY_RATE_EPISODE: float = Field(
        default=0.02,
        gt=0,
        description="Provisional episode decay; tune only with Gate G4 eval evidence.",
    )
    MEMORY_DECAY_RATE_OUTCOME: float = Field(
        default=0.01,
        gt=0,
        description="Provisional outcome decay; tune only with Gate G4 eval evidence.",
    )
    MEMORY_CONFIDENCE_FLOOR: float = Field(
        default=0.05, gt=0, le=1, description="Minimum read-time memory confidence."
    )
    MEMORY_DEFAULT_CONFIDENCE: float = Field(
        default=0.8, ge=0, le=1, description="Initial confidence for a new memory."
    )
    MEMORY_REINFORCE_CONFIDENCE_STEP: float = Field(
        default=0.1,
        gt=0,
        le=1,
        description="Confidence added after explicit duplicate reinforcement.",
    )
    MEMORY_EPISODE_TTL_DAYS: int = Field(
        default=90, gt=0, description="Default lifetime for episode memories."
    )
    MEMORY_OUTCOME_TTL_DAYS: int = Field(
        default=180, gt=0, description="Default lifetime for outcome memories."
    )
    MEMORY_CORE_MAX_PER_SCOPE: int = Field(
        default=20, gt=0, description="Maximum active core memories in one scope tuple."
    )
    MEMORY_CORE_MAX_CHARS: int = Field(
        default=500, gt=0, description="Maximum content characters in one core memory."
    )
    MEMORY_NOTE_MAX_CHARS: int = Field(
        default=2000, gt=0, description="Maximum content characters in one memory note."
    )
    MEMORY_SEARCH_DEFAULT_LIMIT: int = Field(
        default=5, gt=0, description="Default maximum number of memory search results."
    )
    MEMORY_SEARCH_MAX_LIMIT: int = Field(
        default=10, gt=0, description="Maximum accepted memory search result count."
    )
    MEMORY_SEARCH_RESULT_MAX_CHARS: int = Field(
        default=12_000,
        ge=1_000,
        description="Maximum serialized characters returned by the memory search tool.",
    )
    MEMORY_SEARCH_EF_SEARCH: int = Field(
        default=100,
        gt=0,
        description="Per-search HNSW dynamic candidate list size for memory retrieval.",
    )
    MEMORY_CORE_CHAR_BUDGET: int = Field(
        default=2000, gt=0, description="Prompt character budget reserved for core memories."
    )
    MEMORY_SWEEP_INTERVAL_SECONDS: int = Field(
        default=3600, gt=0, description="Interval between expired-memory sweeps."
    )
