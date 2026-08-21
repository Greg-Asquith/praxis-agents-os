# apps/api/tests/services/agents/test_spend_policy.py

"""Google Ads spend tools cannot be weakened below approval."""

import pytest

from core.exceptions.general import AppValidationError
from integrations.google_ads.tools.update_campaign_status import (
    DEFINITION as CAMPAIGN_STATUS_DEFINITION,
)
from integrations.google_ads.tools.update_device_bid_modifiers import (
    DEFINITION as DEVICE_BID_MODIFIER_DEFINITION,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.agents.utils import validate_tool_configuration


@pytest.mark.parametrize(
    "definition",
    [CAMPAIGN_STATUS_DEFINITION, DEVICE_BID_MODIFIER_DEFINITION],
)
def test_google_ads_spend_policy_is_approval_only(monkeypatch, definition) -> None:
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)

    with pytest.raises(AppValidationError):
        validate_tool_configuration(
            tool_names=[definition.name],
            tool_policies={definition.name: "auto"},
        )

    with pytest.raises(ModelConfigurationError):
        definition.to_pydantic_tool(policy="auto")

    assert definition.default_policy == "approval"
    assert definition.supports_auto is False
    assert definition.allowed_policies() == frozenset({"approval"})
