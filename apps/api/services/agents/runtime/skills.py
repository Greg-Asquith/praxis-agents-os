# apps/api/services/agents/runtime/skills.py

"""Internal skill capabilities and loaded-skill helpers for runtime agents."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pydantic_ai.capabilities import AgentCapability, Capability
from pydantic_ai.messages import ModelMessage, ToolCallPart, ToolReturnPart

from models.skills import Skill
from services.agents.runtime.context import RuntimeDeps
from services.skills.documents.domain import SkillDocumentEntry
from services.skills.documents.utils import parse_manifest_entry

SEARCH_SKILLS_TOOL_NAME = "search_skills"
LOAD_SKILL_TOOL_NAME = "load_skill"
READ_SKILL_DOCUMENT_TOOL_NAME = "read_skill_document"
INTERNAL_SKILL_CAPABILITY_PREFIX = "internal-"
INTERNAL_SKILLS_DIR = Path(__file__).parent / "internal_skills"


@dataclass(frozen=True)
class InternalSkill:
    """A skill that ships with the codebase and mounts on every agent."""

    name: str
    human_name: str
    description: str
    instructions: str


@cache
def load_internal_skills() -> tuple[InternalSkill, ...]:
    """Parse the bundled internal skill files once per process."""
    return tuple(_parse_internal_skill(path) for path in sorted(INTERNAL_SKILLS_DIR.glob("*.md")))


def build_internal_skill_capabilities() -> list[AgentCapability[RuntimeDeps]]:
    """Return deferred capabilities for the internal skills every agent receives."""
    return [
        Capability(
            id=f"{INTERNAL_SKILL_CAPABILITY_PREFIX}{skill.name}",
            description=f"{skill.human_name}: {skill.description}",
            instructions=skill.instructions,
            defer_loading=True,
        )
        for skill in load_internal_skills()
    ]


def ready_skill_documents(skill: Skill) -> list[tuple[str, SkillDocumentEntry]]:
    """Return a skill's processed reference documents, sorted by name."""
    ready_entries: list[tuple[str, SkillDocumentEntry]] = []
    for name, value in sorted((skill.documentation_refs or {}).items()):
        entry = parse_manifest_entry(name, value, skill_id=skill.id)
        if entry is not None and entry.status == "ready" and entry.markdown:
            ready_entries.append((name, entry))
    return ready_entries


def loaded_skill_name(call: ToolCallPart) -> str | None:
    """Return the skill name a `load_skill` call asked for."""
    if call.tool_name != LOAD_SKILL_TOOL_NAME:
        return None
    args = call.args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    value = args.get("name") if isinstance(args, dict) else None
    return value if isinstance(value, str) else None


def loaded_skill_names(messages: Sequence[ModelMessage]) -> set[str]:
    """Return the skills this history loaded successfully with `load_skill`."""
    requested: dict[str, str] = {}
    loaded: set[str] = set()
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                name = loaded_skill_name(part)
                if name is not None:
                    requested[part.tool_call_id] = name
            elif isinstance(part, ToolReturnPart) and part.tool_call_id in requested:
                loaded.add(requested[part.tool_call_id])
    return loaded


def _parse_internal_skill(path: Path) -> InternalSkill:
    """Split a Markdown file with `key: value` frontmatter into an internal skill."""
    _, frontmatter, body = path.read_text(encoding="utf-8").split("---\n", 2)
    fields = {
        key.strip(): value.strip()
        for key, value in (line.split(":", 1) for line in frontmatter.splitlines() if line.strip())
    }
    if fields.get("name") != path.stem:
        raise RuntimeError(f"Internal skill {path.name} must declare name: {path.stem}")
    return InternalSkill(
        name=fields["name"],
        human_name=fields["human_name"],
        description=fields["description"],
        instructions=body.strip(),
    )
