# apps/api/tests/services/skills/test_skill_schemas.py

"""Schema regression tests for skill service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from models.skills import Skill
from models.user import User
from services.skills.schemas import SkillRead
from utils.content import ContentScope


def test_skill_read_validates_metadata_from_orm_attribute() -> None:
    """The public metadata alias must not read SQLAlchemy's MetaData registry."""
    now = datetime.now(UTC)
    skill = Skill(
        id=uuid4(),
        name="research",
        human_name="Research",
        description="Research guidance",
        instructions="Use verified sources.",
        scope=ContentScope.WORKSPACE,
        workspace_id=uuid4(),
        created_by=uuid4(),
        documentation_refs={"quick-start": {"markdown": "QUICKSTART.md"}},
        is_active=True,
        metadata_json={"accent": "green"},
        created_at=now,
        updated_at=now,
        deleted=False,
    )

    read_model = SkillRead.from_skill(skill)

    assert read_model.metadata_json == {"accent": "green"}
    assert read_model.model_dump(by_alias=True)["metadata"] == {"accent": "green"}
    assert read_model.documentation_refs == {"quick-start": {"markdown": "QUICKSTART.md"}}


def test_skill_read_never_exposes_the_creator_email() -> None:
    """Platform skills are visible in every workspace, so the creator email must not leak."""
    now = datetime.now(UTC)
    skill = Skill(
        id=uuid4(),
        name="research",
        human_name="Research",
        description="Research guidance",
        instructions="Use verified sources.",
        scope=ContentScope.PLATFORM,
        workspace_id=uuid4(),
        created_by=uuid4(),
        documentation_refs={},
        is_active=True,
        metadata_json={},
        created_at=now,
        updated_at=now,
        deleted=False,
    )
    skill.creator = User(email="alice@agency-a.example", display_name=None)

    assert SkillRead.from_skill(skill).created_by_name is None
