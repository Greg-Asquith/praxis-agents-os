# apps/api/services/agents/runtime/tools/skills.py

"""Runtime tools that let agents find, follow, and write skills."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import case, func, or_, select

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.skills import Skill
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.skills import (
    LOAD_SKILL_TOOL_NAME,
    READ_SKILL_DOCUMENT_TOOL_NAME,
    SEARCH_SKILLS_TOOL_NAME,
    loaded_skill_names,
    ready_skill_documents,
)
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
    update_skill as update_skill_service,
)
from services.skills.documents.domain import SkillDocumentEntry
from services.skills.documents.utils import private_ref_from_key
from services.skills.schemas import (
    SKILL_NAME_PATTERN,
    SkillCreateRequest,
    SkillRead,
    SkillUpdateRequest,
)
from services.skills.utils import visible_skill_filter
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider
from utils.content import ContentScope

SEARCH_SKILLS_LIMIT = 50

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
        "id": str(skill.id),
        "name": skill.name,
        "human_name": skill.human_name,
        "description": skill.description,
        "scope": skill.scope,
        "owner": skill.created_by_name,
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


async def _visible_skill_by_name(
    ctx: RunContext[RuntimeDeps],
    name: str,
    *,
    active_only: bool,
) -> Skill:
    """Return the named skill, preferring a workspace skill over a platform one."""
    filters = [
        Skill.name == name,
        visible_skill_filter(ctx.deps.workspace),
        Skill.deleted == False,  # noqa: E712
    ]
    if active_only:
        filters.append(Skill.is_active.is_(True))
    skill = await ctx.deps.db.scalar(
        select(Skill)
        .where(*filters)
        .order_by(case((Skill.scope == ContentScope.WORKSPACE, 0), else_=1))
        .limit(1)
    )
    if skill is None:
        raise ModelRetry(
            f"No skill named {name!r}. Call {SEARCH_SKILLS_TOOL_NAME} to see valid names."
        )
    return skill


def _search_rank(query: str | None):
    """Return a filter and rank that match any query word in a skill's name or description."""
    terms = [term for term in (query or "").split() if len(term) > 1][:10]
    if not terms:
        return None, None
    matches = [
        or_(
            Skill.name.ilike(f"%{term}%"),
            Skill.human_name.ilike(f"%{term}%"),
            Skill.description.ilike(f"%{term}%"),
        )
        for term in terms
    ]
    rank = case((matches[0], 1), else_=0)
    for match in matches[1:]:
        rank = rank + case((match, 1), else_=0)
    return or_(*matches), rank


@runtime_tool(
    name=SEARCH_SKILLS_TOOL_NAME,
    defer_loading=False,
    provider="core",
    label="Search Skills",
    code_eligible=False,
    description=(
        "Find skills: saved instructions for doing a kind of task well. Pass words that "
        "describe the task, or omit query to list every skill. Load a match with load_skill."
    ),
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Searching Skills",
        completed_label="Searched Skills",
        failed_label="Couldn't Search Skills",
        arg_fields=(ToolFieldPresentation(key="query", label="Search"),),
        result_fields=(ToolFieldPresentation(key="skills", label="Skills", format="list"),),
    ),
)
async def search_skills(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str | None, Field(max_length=200)] = None,
) -> dict[str, object]:
    """Return active skills visible in this workspace, best matches first."""
    match, rank = _search_rank(query)
    statement = select(Skill).where(
        visible_skill_filter(ctx.deps.workspace),
        Skill.deleted == False,  # noqa: E712
        Skill.is_active.is_(True),
    )
    order_by = [case((Skill.scope == ContentScope.WORKSPACE, 0), else_=1), Skill.name]
    if match is not None:
        statement = statement.where(match)
        order_by.insert(0, rank.desc())
    total = await ctx.deps.db.scalar(select(func.count()).select_from(statement.subquery()))
    skills = await ctx.deps.db.scalars(statement.order_by(*order_by).limit(SEARCH_SKILLS_LIMIT))
    return {
        "skills": [_skill_summary(SkillRead.from_skill(skill)) for skill in skills],
        "total": total or 0,
    }


@runtime_tool(
    name=LOAD_SKILL_TOOL_NAME,
    defer_loading=False,
    provider="core",
    label="Load Skill",
    code_eligible=False,
    description=(
        "Load a skill's full instructions by name. Follow them for the task, and read "
        "them before updating the skill."
    ),
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Loading Skill {name}",
        completed_label="Loaded Skill {name}",
        failed_label="Couldn't Load Skill",
        arg_fields=(ToolFieldPresentation(key="name", label="Skill"),),
    ),
)
async def load_skill(ctx: RunContext[RuntimeDeps], name: SkillName) -> dict[str, object]:
    """Return one active skill's instructions and record that it was used."""
    skill = await _visible_skill_by_name(ctx, name, active_only=True)
    result: dict[str, object] = {
        **_skill_summary(SkillRead.from_skill(skill)),
        "instructions": skill.instructions,
    }
    documents = [
        {"name": document_name, "filename": entry.filename}
        for document_name, entry in ready_skill_documents(skill)
    ]
    if documents:
        result["documents"] = documents
        result["documents_note"] = f"Read these with {READ_SKILL_DOCUMENT_TOOL_NAME}."
    # Tenant sessions can't write platform rows, so only workspace skills track use.
    if skill.scope == ContentScope.WORKSPACE:
        skill.last_used_at = datetime.now(UTC)
        await ctx.deps.db.flush()
    return result


@runtime_tool(
    name=READ_SKILL_DOCUMENT_TOOL_NAME,
    defer_loading=False,
    provider="core",
    label="Read Skill Document",
    code_eligible=False,
    description="Read one of a loaded skill's reference documents as Markdown.",
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=30,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="sparkles",
        running_label="Reading Skill Document",
        completed_label="Read Skill Document",
        failed_label="Couldn't Read Skill Document",
        arg_fields=(
            ToolFieldPresentation(key="skill", label="Skill"),
            ToolFieldPresentation(key="document", label="Document"),
        ),
    ),
)
async def read_skill_document(
    ctx: RunContext[RuntimeDeps],
    skill: SkillName,
    document: Annotated[str, Field(min_length=1, max_length=255)],
) -> str:
    """Read a reference document from a skill this conversation has loaded."""
    if skill not in loaded_skill_names(ctx.messages):
        raise ModelRetry(f"Call {LOAD_SKILL_TOOL_NAME} for {skill!r} before reading its documents.")
    matched = await _visible_skill_by_name(ctx, skill, active_only=True)
    document_name, entry = _resolve_ready_document(matched, document)
    try:
        data = await get_storage_provider().get_object(private_ref_from_key(entry.markdown))
    except StorageNotFoundError:
        raise ModelRetry("Document content is unavailable.") from None
    content = data.decode("utf-8", errors="replace")
    return (
        f"<skill-document skill={skill!r} document={document_name!r}>\n{content}\n</skill-document>"
    )


def _resolve_ready_document(skill: Skill, document: str) -> tuple[str, SkillDocumentEntry]:
    requested = document.strip()
    ready_entries = ready_skill_documents(skill)
    for name, entry in ready_entries:
        if name == requested:
            return name, entry
    filename_matches = [
        (name, entry)
        for name, entry in ready_entries
        if entry.filename.casefold() == requested.casefold()
    ]
    if len(filename_matches) == 1:
        return filename_matches[0]
    if len(filename_matches) > 1:
        matching_names = ", ".join(name for name, _entry in filename_matches)
        raise ModelRetry(
            f"Document filename is ambiguous. Use one of these document names: {matching_names}."
        )
    valid_documents = (
        ", ".join(f"{name} ({entry.filename})" for name, entry in ready_entries) or "none"
    )
    raise ModelRetry(
        f"Unknown or unavailable document. Ready documents by name or filename: {valid_documents}."
    )


@runtime_tool(
    name="create_skill",
    provider="core",
    label="Create Skill",
    code_eligible=False,
    description=(
        "Save a new skill. Load the skill-authoring guide and agree the content with the "
        "user first. Once saved, every agent that can see it finds it with search_skills."
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
        approval_title="Create a Skill",
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
        "Change a skill. Call load_skill first. Instructions replace the whole text, so "
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
    target = await _visible_skill_by_name(ctx, name, active_only=False)
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
