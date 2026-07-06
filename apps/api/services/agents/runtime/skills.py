# apps/api/services/agents/runtime/skills.py

"""Build deferred skill capabilities for runtime agents."""

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.capabilities import AgentCapability, Capability

from models.agent_run import AgentRun
from models.skills import Skill
from services.agents.runtime.context import RuntimeDeps
from services.skills.documents.domain import SkillDocumentEntry
from services.skills.documents.utils import (
    parse_manifest_entry,
    private_ref_from_key,
)
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)

SKILL_CAPABILITY_PREFIX = "skill:"
SKILL_DOCUMENTS_CAPABILITY_ID = "skills-documents"
READ_SKILL_DOCUMENT_TOOL_NAME = "read_skill_document"


def skill_capability_id(skill: Skill) -> str:
    """Return the stable deferred-capability id for a skill."""
    return f"{SKILL_CAPABILITY_PREFIX}{skill.id}"


def build_skill_capabilities(
    skills: Sequence[Skill],
) -> list[AgentCapability[RuntimeDeps]]:
    """Return Pydantic AI capabilities for assigned runtime skills."""
    capabilities: list[AgentCapability[RuntimeDeps]] = [
        Capability(
            id=skill_capability_id(skill),
            description=_catalog_description(skill),
            instructions=_loaded_instructions(skill),
            defer_loading=True,
        )
        for skill in skills
    ]
    if any(_ready_document_entries(skill) for skill in skills):
        capabilities.append(
            Capability(
                id=SKILL_DOCUMENTS_CAPABILITY_ID,
                instructions=(
                    "Some skills provide reference documents. Load a skill with "
                    "load_capability before reading its documents."
                ),
                tools=[_build_read_skill_document_tool(skills)],
            )
        )
    return capabilities


def record_skill_activation(
    skills: Sequence[Skill],
    part: Any,
    *,
    run: AgentRun,
) -> None:
    """Record that a runtime run loaded one of its assigned skill capabilities."""
    capability_id = _capability_id_from_args(getattr(part, "args", None))
    if capability_id is None or not capability_id.startswith(SKILL_CAPABILITY_PREFIX):
        return

    for skill in skills:
        if skill_capability_id(skill) != capability_id:
            continue
        skill.last_used_at = datetime.now(UTC)
        logger.info(
            "Recorded runtime skill activation",
            extra={
                "run_id": str(run.id),
                "agent_id": str(run.agent_id),
                "skill_id": str(skill.id),
            },
        )
        return


def _catalog_description(skill: Skill) -> str:
    return f"{skill.human_name or skill.name}: {skill.description}"


def _loaded_instructions(skill: Skill) -> str:
    ready_documents = _ready_document_entries(skill)
    if not ready_documents:
        return skill.instructions

    lines = [
        skill.instructions.rstrip(),
        "",
        "## Skill documents",
        "",
        (
            f"Read these with {READ_SKILL_DOCUMENT_TOOL_NAME}"
            f'(skill="{skill.name}", document="<name-or-filename>"):'
        ),
    ]
    lines.extend(f"- {name}: {entry.filename}" for name, entry in ready_documents)
    return "\n".join(lines)


def _ready_document_entries(skill: Skill) -> list[tuple[str, SkillDocumentEntry]]:
    manifest = skill.documentation_refs or {}
    if not manifest:
        return []

    ready_entries: list[tuple[str, SkillDocumentEntry]] = []
    for name, value in sorted(manifest.items()):
        entry = parse_manifest_entry(name, value, skill_id=skill.id)
        if entry is not None and entry.status == "ready" and entry.markdown:
            ready_entries.append((name, entry))
    return ready_entries


def _build_read_skill_document_tool(
    skills: Sequence[Skill],
) -> Tool[RuntimeDeps]:
    skills_by_name = {skill.name: skill for skill in skills}

    async def read_skill_document(
        ctx: RunContext[RuntimeDeps],
        skill: str,
        document: str,
    ) -> str:
        """Read one of a loaded skill's reference documents as markdown."""
        matched = skills_by_name.get(skill)
        if matched is None:
            valid_names = ", ".join(sorted(skills_by_name)) or "none"
            raise ModelRetry(f"Unknown skill. Valid skills: {valid_names}.")

        required_capability_id = skill_capability_id(matched)
        if required_capability_id not in ctx.loaded_capability_ids:
            raise ModelRetry(
                f'Call load_capability with id="{required_capability_id}" '
                "before reading its documents."
            )

        document_name, entry = _resolve_ready_document(matched, document)

        provider = get_storage_provider()
        try:
            data = await provider.get_object(private_ref_from_key(entry.markdown))
        except StorageNotFoundError:
            raise ModelRetry("Document content is unavailable.") from None

        content = data.decode("utf-8", errors="replace")
        return (
            f"<skill-document skill={skill!r} document={document_name!r}>\n"
            f"{content}\n"
            "</skill-document>"
        )

    return Tool(
        read_skill_document,
        takes_ctx=True,
        name=READ_SKILL_DOCUMENT_TOOL_NAME,
        description="Read one of a loaded skill's reference documents as markdown.",
    )


def _resolve_ready_document(skill: Skill, document: str) -> tuple[str, SkillDocumentEntry]:
    requested = document.strip()
    ready_entries = _ready_document_entries(skill)

    for name, entry in ready_entries:
        if name == requested:
            return name, entry

    filename_matches = [
        (name, entry) for name, entry in ready_entries if entry.filename == requested
    ]
    if not filename_matches:
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

    valid_documents = ", ".join(_ready_document_labels(ready_entries)) or "none"
    raise ModelRetry(
        f"Unknown or unavailable document. Ready documents by name or filename: {valid_documents}."
    )


def _ready_document_labels(
    ready_entries: Sequence[tuple[str, SkillDocumentEntry]],
) -> list[str]:
    return [f"{name} ({entry.filename})" for name, entry in ready_entries]


def _capability_id_from_args(args: object) -> str | None:
    parsed_args = args
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed_args, dict):
        return None

    value = parsed_args.get("id")
    return value if isinstance(value, str) else None
