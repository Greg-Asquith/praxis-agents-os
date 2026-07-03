# apps/api/tests/services/skills/test_skill_schemas.py

"""Schema regression tests for skill service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from models.skills import Skill
from services.skills.schemas import SkillCreateRequest, SkillRead


@pytest.mark.parametrize(
    "name",
    ["research", "google-ads", "a1-b2"],
)
def test_skill_create_accepts_lowercase_kebab_names(name: str) -> None:
    payload = SkillCreateRequest(
        name=f" {name} ",
        description="Use this for focused work.",
        instructions="Follow the workflow.",
    )

    assert payload.name == name


@pytest.mark.parametrize(
    "name",
    ["Bad Name", "-leading", "trailing-", "two--hyphens", "Uppercase"],
)
def test_skill_create_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        SkillCreateRequest(
            name=name,
            description="Use this for focused work.",
            instructions="Follow the workflow.",
        )


def test_skill_create_enforces_description_prompt_budget() -> None:
    with pytest.raises(ValidationError):
        SkillCreateRequest(
            name="too-long",
            description="x" * 1025,
            instructions="Follow the workflow.",
        )


def test_skill_read_validates_metadata_from_orm_attribute() -> None:
    """The public metadata alias must not read SQLAlchemy's MetaData registry."""
    now = datetime.now(UTC)
    skill = Skill(
        id=uuid4(),
        name="research",
        human_name="Research",
        description="Research guidance",
        instructions="Use verified sources.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        documentation_refs={"quick-start": {"markdown": "QUICKSTART.md"}},
        is_active=True,
        is_favorite=False,
        metadata_json={"accent": "green"},
        created_at=now,
        updated_at=now,
        deleted=False,
    )

    read_model = SkillRead.from_skill(skill)

    assert read_model.metadata_json == {"accent": "green"}
    assert read_model.model_dump(by_alias=True)["metadata"] == {"accent": "green"}
    assert read_model.documentation_refs == {
        "quick-start": {"markdown": "QUICKSTART.md"}
    }
