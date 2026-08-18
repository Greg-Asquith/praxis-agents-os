# apps/api/services/agents/runtime/tools/workspace_tools.py

"""Load runtime tool definitions synthesized from workspace-owned rows.

Future workspace-defined tool families add a producer, reserve a unique name
prefix, and contribute one call in the aggregation loader below. The registry,
mounting, dispatch, and presentation seams consume only generic definitions.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.classifiers import Classifier
from models.workspace import Workspace
from services.agents.runtime.tools.contract import RuntimeToolDefinition

RESERVED_WORKSPACE_TOOL_PREFIXES = ("classifier_",)


async def load_workspace_tool_definitions(
    db: AsyncSession,
    workspace: Workspace,
) -> list[RuntimeToolDefinition]:
    """Load all active workspace-defined runtime tools for one run or request."""
    from services.agents.runtime.tools.classifiers import build_classifier_tool_definitions

    classifiers = list(
        await db.scalars(
            select(Classifier)
            .where(
                Classifier.workspace_id == workspace.id,
                Classifier.deleted.is_(False),
                Classifier.is_active.is_(True),
            )
            .order_by(Classifier.name)
        )
    )
    return build_classifier_tool_definitions(classifiers)


def workspace_tool_names(definitions: Sequence[RuntimeToolDefinition]) -> frozenset[str]:
    """Return the names accepted by workspace-scoped agent configuration."""
    return frozenset(definition.name for definition in definitions if definition.configurable)
