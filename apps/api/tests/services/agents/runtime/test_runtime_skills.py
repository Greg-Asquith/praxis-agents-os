# apps/api/tests/services/agents/runtime/test_runtime_skills.py

"""Tests for bundled internal skills."""

import pytest

from services.agents.runtime.skills import INTERNAL_SKILLS_DIR, load_internal_skills

pytestmark = pytest.mark.asyncio


async def test_every_bundled_internal_skill_parses_within_skill_limits() -> None:
    skills = load_internal_skills()

    assert [skill.name for skill in skills] == sorted(
        path.stem for path in INTERNAL_SKILLS_DIR.glob("*.md")
    )
    for skill in skills:
        assert skill.human_name
        assert 0 < len(skill.description) <= 1024
        assert 0 < len(skill.instructions) <= 20000
        assert not skill.instructions.startswith("---")
