# apps/api/services/agents/runtime/tools/skill_authoring.py

"""Runtime tools that let agents read and write workspace skills."""

from typing import Annotated

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import case, select

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.skills import Skill
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.skills import (
    create_skill as create_skill_service,
    list_skills as list_skills_service,
    update_skill as update_skill_service,
)
from services.skills.schemas import (
    SKILL_NAME_PATTERN,
    SkillCreateRequest,
    SkillRead,
    SkillUpdateRequest,
)
from services.skills.utils import visible_skill_filter
from utils.content import ContentScope

LIST_SKILLS_LIMIT = 100

SkillName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=SKILL_NAME_PATTERN,
        description="Lowercase words joined by hyphens, such as weekly-client-report.",
    ),
]
SkillHumanName = Annotated[str, Field(min_length=1, max_length=255)]
SkillDescription = Annotated[
    str,
    Field(
        min_length=1,
        max_length=1024,
        description="What the skill does and when an agent must use it.",
    ),
]
SkillInstructions = Annotated[
    str,
    Field(min_length=1, max_length=20000, description="The complete Markdown instructions."),
]

_SKILL_TEXT_FIELDS = (
    ToolFieldPresentation(key="human_name", label="Display Name", editable=True),
    ToolFieldPresentation(
        key="description",
        label="When to Use",
        format="multiline",
        editable=True,
    ),
    ToolFieldPresentation(
        key="instructions",
        label="Instructions",
        format="markdown",
        editable=True,
    ),
)


def _skill_summary(skill: SkillRead) -> dict[str, object]:
    return {
        "name": skill.name,
        "human_name": skill.human_name,
        "description": skill.description,
        "scope": skill.scope,
        "owner": skill.created_by_name,
        "is_active": skill.is_active,
    }


_SERVICE_ERRORS = (
    ValidationError,
    AppValidationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
)


def _service_retry(exc: Exception) -> ModelRetry:
    if isinstance(exc, ValidationError):
        return ModelRetry(f"Invalid skill fields: {exc.errors(include_url=False)}")
    return ModelRetry(getattr(exc, "message", str(exc)))


async def _visible_skill_by_name(ctx: RunContext[RuntimeDeps], name: str) -> Skill:
    """Return the named skill, preferring a workspace skill over a platform one."""
    skill = await ctx.deps.db.scalar(
        select(Skill)
        .where(
            Skill.name == name,
            visible_skill_filter(ctx.deps.workspace),
            Skill.deleted == False,  # noqa: E712
        )
        .order_by(case((Skill.scope == ContentScope.WORKSPACE, 0), else_=1))
        .limit(1)
    )
    if skill is None:
        raise ModelRetry(f"No skill named {name!r}. Call list_skills to see valid names.")
    return skill


@runtime_tool(
    name="list_skills",
    provider="core",
    label="List Skills",
    code_eligible=False,
    description="List the workspace and platform skills, including inactive ones, by name.",
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Listing Skills",
        completed_label="Listed Skills",
        failed_label="Couldn't List Skills",
        result_fields=(ToolFieldPresentation(key="skills", label="Skills", format="list"),),
    ),
)
async def list_skills(ctx: RunContext[RuntimeDeps]) -> dict[str, object]:
    """List skills visible in this workspace, newest first."""
    result = await list_skills_service(
        ctx.deps.db,
        workspace=ctx.deps.workspace,
        limit=LIST_SKILLS_LIMIT,
        offset=0,
        include_inactive=True,
    )
    return {
        "skills": [_skill_summary(skill) for skill in result.skills],
        "total": result.total,
    }


@runtime_tool(
    name="read_skill",
    provider="core",
    label="Read Skill",
    code_eligible=False,
    description="Read a skill's full instructions by name. Read a skill before updating it.",
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Reading Skill {name}",
        completed_label="Read Skill {name}",
        failed_label="Couldn't Read Skill",
        arg_fields=(ToolFieldPresentation(key="name", label="Skill"),),
    ),
)
async def read_skill(ctx: RunContext[RuntimeDeps], name: SkillName) -> dict[str, object]:
    """Return one visible skill with its full instructions."""
    skill = await _visible_skill_by_name(ctx, name)
    return {**_skill_summary(SkillRead.from_skill(skill)), "instructions": skill.instructions}


@runtime_tool(
    name="create_skill",
    provider="core",
    label="Create Skill",
    code_eligible=False,
    description=(
        "Save a new skill. Load the skill-authoring guide and agree the content with the "
        "user first. "
        "Assigning it to agents happens in the agent editor."
    ),
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Creating Skill",
        completed_label="Created Skill {human_name}",
        failed_label="Couldn't Create Skill",
        approval_title="Create skill?",
        approval_prompt="Review this skill before it is saved.",
        approve_label="Create Skill",
        arg_fields=(
            ToolFieldPresentation(key="name", label="Name", editable=True),
            *_SKILL_TEXT_FIELDS,
            ToolFieldPresentation(
                key="share_with_all_workspaces",
                label="Make Available to Every Workspace",
                format="boolean",
                editable=True,
            ),
        ),
    ),
)
async def create_skill(
    ctx: RunContext[RuntimeDeps],
    name: SkillName,
    human_name: SkillHumanName,
    description: SkillDescription,
    instructions: SkillInstructions,
    share_with_all_workspaces: Annotated[
        bool,
        Field(description="True only when the user asks to share the skill with every workspace."),
    ],
) -> dict[str, object]:
    """Create one active skill attributed to the run's user, optionally for every workspace."""
    try:
        skill = await create_skill_service(
            ctx.deps.db,
            request=None,
            actor=ctx.deps.user,
            workspace=ctx.deps.workspace,
            membership=ctx.deps.membership,
            payload=SkillCreateRequest(
                name=name,
                human_name=human_name,
                description=description,
                instructions=instructions,
                scope=(
                    ContentScope.PLATFORM if share_with_all_workspaces else ContentScope.WORKSPACE
                ),
            ),
        )
    except _SERVICE_ERRORS as exc:
        raise _service_retry(exc) from exc
    return {"status": "created", "skill": _skill_summary(skill)}


@runtime_tool(
    name="update_skill",
    provider="core",
    label="Update Skill",
    code_eligible=False,
    description=(
        "Change a skill. Call read_skill first. Instructions replace the whole text, so "
        "send the complete revised version. Omit fields that stay the same. A skill shared "
        "with every workspace can be changed only by the person who shared it."
    ),
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Updating Skill {name}",
        completed_label="Updated Skill {name}",
        failed_label="Couldn't Update Skill",
        approval_title="Update skill?",
        approval_prompt="Review these changes. Every agent using this skill follows them.",
        approve_label="Update Skill",
        arg_fields=(ToolFieldPresentation(key="name", label="Skill"), *_SKILL_TEXT_FIELDS),
    ),
)
async def update_skill(
    ctx: RunContext[RuntimeDeps],
    name: SkillName,
    human_name: SkillHumanName | None = None,
    description: SkillDescription | None = None,
    instructions: SkillInstructions | None = None,
) -> dict[str, object]:
    """Update one visible skill under the same permissions as the Skills page."""
    target = await _visible_skill_by_name(ctx, name)
    changes = {
        field: value
        for field, value in (
            ("human_name", human_name),
            ("description", description),
            ("instructions", instructions),
        )
        if value is not None
    }
    if not changes:
        raise ModelRetry("Provide at least one of human_name, description, or instructions.")
    try:
        skill = await update_skill_service(
            ctx.deps.db,
            request=None,
            actor=ctx.deps.user,
            workspace=ctx.deps.workspace,
            membership=ctx.deps.membership,
            skill_id=target.id,
            payload=SkillUpdateRequest(**changes),
        )
    except _SERVICE_ERRORS as exc:
        raise _service_retry(exc) from exc
    return {"status": "updated", "skill": _skill_summary(skill)}
