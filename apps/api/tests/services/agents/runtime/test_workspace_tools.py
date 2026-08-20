"""Runtime contract tests for workspace-defined classifier tools."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from models.classifiers import Classifier
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools.classifiers import build_classifier_tool_definitions
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.native.classifier import ClassifiedItem
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_tools,
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
            settings={},
            max_steps=2,
        ),
    )


def test_classifier_builder_emits_flat_code_eligible_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_model_resolution(monkeypatch)
    definitions = build_classifier_tool_definitions(
        [_classifier("complaint_triage"), _classifier("sentiment")]
    )

    assert [definition.name for definition in definitions] == [
        "classifier_complaint_triage",
        "classifier_sentiment",
    ]
    assert all(definition.provider == "classifier" for definition in definitions)
    assert all(definition.code_eligible for definition in definitions)
    assert all(definition.allowed_policies() == {"auto"} for definition in definitions)
    for definition in definitions:
        schema = definition.serialized_input_schema()
        assert schema is not None
        assert schema["required"] == ["items"]
        assert set(schema["properties"]) == {"items"}
        assert "$defs" not in schema

    static_classify = RUNTIME_TOOL_CATALOG["classify"]
    catalog = CodeModeCatalog.build(
        [(static_classify, "auto"), *((definition, "auto") for definition in definitions)]
    )
    assert "def classify(" in catalog.stub_text
    assert "def classifier_complaint_triage(" in catalog.stub_text
    assert "def classifier_sentiment(" in catalog.stub_text


def test_inactive_classifier_is_not_synthesized(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_model_resolution(monkeypatch)
    assert build_classifier_tool_definitions([_classifier("inactive", active=False)]) == []


def test_classifier_with_unavailable_provider_is_not_synthesized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(**_kwargs):
        from pydantic_ai import ModelRetry

        raise ModelRetry("Provider is not configured for native classify.")

    monkeypatch.setattr(
        "services.agents.runtime.tools.classifiers.resolve_classifier_model",
        unavailable,
    )

    assert build_classifier_tool_definitions([_classifier("unavailable")]) == []


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


def test_workspace_definition_mounts_directly_and_in_code_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_model_resolution(monkeypatch)
    definition = build_classifier_tool_definitions([_classifier("complaint_triage")])[0]
    direct_agent = SimpleNamespace(
        id=uuid4(),
        tool_names=[definition.name],
        tool_policies={},
        code_mode_enabled=False,
    )
    assert definition.name in {
        tool.name for tool in build_runtime_tools(direct_agent, workspace_definitions=[definition])
    }

    code_agent = SimpleNamespace(
        id=uuid4(),
        tool_names=[definition.name],
        tool_policies={},
        code_mode_enabled=True,
    )
    wrapped: list[str] = []
    tools = build_runtime_tools(
        code_agent,
        workspace_definitions=[definition],
        wrapped_tool_names=wrapped,
    )
    assert definition.name in wrapped
    assert "run_workflow" in {tool.name for tool in tools}


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
