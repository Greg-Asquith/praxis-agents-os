# apps/api/tests/services/skills/test_skill_schemas.py

"""Schema regression tests for skill service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from models.skills import Skill
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
