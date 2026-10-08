# apps/api/services/agents/runtime/subagents/resolve_subagent_model.py

"""Choose a sub-agent's model without exceeding the parent's tier."""

from models.agent import Agent
from models.workspace import Workspace
from services.agents.models import find_model, list_models
from services.agents.models.domain import PROVIDER_AZURE, ModelType
from services.agents.models.resolution import effective_model_pair, workspace_default_model
from services.agents.models.utils import is_model_available

_TIER_RANK: dict[ModelType, int] = {"light": 0, "standard": 1, "powerful": 2, "max": 3}


def resolve_subagent_model(
    parent: Agent,
    *,
    workspace: Workspace,
    model_tier: ModelType | None,
) -> tuple[str, str]:
    """Return the sub-agent's provider and model.

    A tier picks the newest active model of that tier from the parent's
    provider; no tier uses the workspace default model. Either falls back to the
    parent's model when nothing matches or the choice ranks above the parent.
    Azure parents always keep their own deployment.
    """
    parent_pair = effective_model_pair(parent, workspace=workspace)
    if model_tier is None:
        default_info = find_model(*workspace_default_model(workspace))
        candidate = (
            default_info
            if default_info and not default_info.deprecated and is_model_available(default_info)
            else None
        )
    else:
        candidate = _tier_candidate(parent_pair[0], model_tier)
    if candidate is None or not within_parent_model(
        parent, workspace=workspace, model_provider=candidate.provider, model=candidate.model
    ):
        return parent_pair
    return candidate.provider, candidate.model


def within_parent_model(
    parent: Agent, *, workspace: Workspace, model_provider: str, model: str
) -> bool:
    """Return whether a sub-agent model ranks no higher than the parent's effective model."""
    parent_pair = effective_model_pair(parent, workspace=workspace)
    if (model_provider, model) == parent_pair:
        return True
    parent_info = find_model(*parent_pair)
    child_info = find_model(model_provider, model)
    if parent_pair[0] == PROVIDER_AZURE or parent_info is None or child_info is None:
        return False
    return _TIER_RANK[child_info.model_type] <= _TIER_RANK[parent_info.model_type]


def _tier_candidate(provider: str, model_tier: ModelType):
    # The catalog lists each provider's newest model first.
    return next(
        (
            info
            for info in list_models()
            if info.provider == provider
            and info.model_type == model_tier
            and info.supports_tools
            and is_model_available(info)
        ),
        None,
    )
