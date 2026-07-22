# apps/api/tests/services/agents/test_spend_policy.py

"""Google Ads spend tools cannot be weakened below approval."""

import pytest

from core.exceptions.general import AppValidationError
from integrations.google_ads.tools.update_campaign_status import DEFINITION
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.agents.utils import validate_tool_configuration


def test_google_ads_spend_policy_is_approval_only(monkeypatch) -> None:
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, DEFINITION.name, DEFINITION)

    with pytest.raises(AppValidationError):
        validate_tool_configuration(
            tool_names=[DEFINITION.name],
            tool_policies={DEFINITION.name: "auto"},
        )

    with pytest.raises(ModelConfigurationError):
        DEFINITION.to_pydantic_tool(policy="auto")

    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.allowed_policies() == frozenset({"approval"})
