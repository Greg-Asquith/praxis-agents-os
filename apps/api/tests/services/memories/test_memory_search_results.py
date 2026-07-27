"""Memory search limits and model-visible output bounds."""

import json

from core.settings import settings
from services.agents.runtime.tools.memory_results import build_bounded_search_output
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG


def _hit(index: int) -> dict[str, object]:
    return {
        "id": f"memory-{index}",
        "scope": "workspace",
        "kind": "note",
        "memory_type": "fact",
        "title": f"Memory {index}",
        "content": "\\quoted\n" * settings.MEMORY_NOTE_MAX_CHARS,
        "source": "interactive",
        "created_by": "agent",
        "created_by_user_id": None,
        "effective_confidence": 0.8,
        "score": 0.1,
    }


def test_memory_search_limits_are_small_and_schema_pinned() -> None:
    assert settings.MEMORY_NOTE_MAX_CHARS == 2_000
    assert settings.MEMORY_SEARCH_DEFAULT_LIMIT == 5
    assert settings.MEMORY_SEARCH_MAX_LIMIT == 10
    schema = RUNTIME_TOOL_CATALOG["search_memory"].serialized_input_schema()
    assert schema is not None
    assert schema["properties"]["limit"]["default"] == 5
    assert schema["properties"]["limit"]["maximum"] == 10


def test_structured_search_output_stays_within_its_exact_budget() -> None:
    output = build_bounded_search_output(
        query="durable client context",
        hits=[_hit(index) for index in range(settings.MEMORY_SEARCH_MAX_LIMIT)],
        used_lexical_fallback=False,
        max_chars=settings.MEMORY_SEARCH_RESULT_MAX_CHARS,
    )

    serialized = json.dumps(
        output,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert len(serialized) <= settings.MEMORY_SEARCH_RESULT_MAX_CHARS
    assert output["results_truncated"] is True
    assert output["total"] < output["matches_found"]
    assert output["next_step"]
