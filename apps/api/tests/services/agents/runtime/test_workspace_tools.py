"""Runtime contract tests for workspace-defined classifier tools."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from models.classifiers import Classifier
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.tools.classifiers import build_classifier_tool_definitions
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.native.classifier import ClassifiedItem
from services.agents.runtime.tools.registry import (
    register_tool_definition,
)
from services.agents.runtime.tools.workspace_tools import RESERVED_WORKSPACE_TOOL_PREFIXES


def _classifier(name: str, *, active: bool = True) -> Classifier:
    now = datetime.now(UTC)
    return Classifier(
        id=uuid4(),
        workspace_id=uuid4(),
        created_by=uuid4(),
        name=name,
        display_name=name.replace("_", " ").title(),
        description="Classify support messages.",
        instructions="Use the message's primary intent.",
        labels=[
            {"label": "complaint", "description": "Needs recovery."},
            {"label": "other", "description": None},
        ],
        is_active=active,
        deleted=False,
        created_at=now,
        updated_at=now,
    )


def _patch_model_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.classifiers.resolve_classifier_model",
        lambda **_kwargs: ResolvedModel(
            provider="openai",
            model="gpt-5.6-luna",
            transport_model="gpt-5.6-luna",
            settings={},
            max_steps=2,
        ),
    )


async def test_workspace_classifier_reuses_dynamic_runner_with_classifier_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_model_resolution(monkeypatch)
    row = _classifier("complaint_triage")
    captured: dict[str, object] = {}

    async def run(_deps, **kwargs):
        captured.update(kwargs)
        return [ClassifiedItem(index=0, value="Refund please", label="complaint")]

    monkeypatch.setattr(
        "services.agents.runtime.tools.classifiers.run_native_classification",
        run,
    )
    definition = build_classifier_tool_definitions([row])[0]
    output = await definition.function(
        SimpleNamespace(deps=SimpleNamespace()),
        ["Refund please"],
    )

    assert captured["labels"] == ["complaint", "other"]
    assert captured["event_details"] == {
        "classifier_id": str(row.id),
        "classifier_name": "complaint_triage",
    }
    assert output["results"] == [{"index": 0, "value": "Refund please", "label": "complaint"}]


def test_static_registration_rejects_reserved_workspace_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = RuntimeToolDefinition(
        name="classifier_static_collision",
        function=lambda: None,
        description="Must not register.",
    )
    with pytest.raises(RuntimeError, match="reserved workspace-defined prefix"):
        register_tool_definition(definition)

    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.RESERVED_WORKSPACE_TOOL_PREFIXES",
        (*RESERVED_WORKSPACE_TOOL_PREFIXES, "extractor_"),
    )
    with pytest.raises(RuntimeError, match="reserved workspace-defined prefix"):
        register_tool_definition(
            RuntimeToolDefinition(
                name="extractor_static_collision",
                function=lambda: None,
                description="Must not register.",
            )
        )
