"""SharePoint approval destinations and private display metadata."""

from dataclasses import replace

import pytest
from pydantic import ValidationError
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart

from integrations.sharepoint.tools import TOOL_DEFINITIONS
from services.agents.runtime.approval_events import add_approval_display_args
from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata
from services.agents.runtime.staged_tool_content import (
    tool_args_for_display,
    tool_replay_args_for_editing,
)
from tests.integrations.sharepoint.support import context, entry

WRITES = tuple(definition for definition in TOOL_DEFINITIONS if definition.effect == "write")
LABEL = '<img src=x onerror="alert(1)"> [Library](javascript:alert(1)) {_target}'
ARGS = {
    "sharepoint_create_folder": {"name": "Reports"},
    "sharepoint_write_file": {"name": "report.txt", "content": "Reviewed text"},
    "sharepoint_update_file": {
        "file": {"drive_id": "drive", "item_id": "file", "kind": "file"},
        "expected_version": '"version-1"',
        "content": "Reviewed text",
    },
}


@pytest.mark.parametrize("definition", WRITES, ids=lambda value: value.name)
@pytest.mark.parametrize("nested", [False, True], ids=["direct", "code_mode"])
async def test_library_display_is_retained_without_becoming_replay_arguments(
    monkeypatch, definition, nested
):
    selected = replace(entry(), write_allowed=True, display_name=LABEL)
    deps = context(selected).deps
    deps.workspace_tool_definitions = ()
    monkeypatch.setattr(
        "services.agents.runtime.approval_events.resolve_runtime_tool_definition",
        lambda _name, _definitions: definition,
    )
    args = ARGS[definition.name]
    call = ToolCallPart(definition.name, args, "write")
    outer = (
        ToolCallPart("run_workflow", {"code": "retained workflow"}, "workflow") if nested else call
    )
    metadata = (
        {
            outer.tool_call_id: build_code_mode_approval_metadata(
                outer_tool_call_id=outer.tool_call_id,
                nested_call=call,
                reason="Review the write.",
            )
        }
        if nested
        else {}
    )
    enriched = await add_approval_display_args(
        deps, DeferredToolRequests(approvals=[outer], metadata=metadata)
    )
    retained = enriched.metadata[outer.tool_call_id]
    display = tool_args_for_display(tool_name=call.tool_name, args=args, metadata=retained)
    assert display["_library"] == LABEL
    assert display["_target"] == {
        "drive_id": selected.external_id,
        "resource_id": str(selected.integration_resource_id),
        "connection_id": str(selected.connection_id),
    }
    assert (
        tool_replay_args_for_editing(tool_name=call.tool_name, args=args, metadata=retained) == args
    )
    validator = definition.to_pydantic_tool().function_schema.validator
    for key in ("_library", "_target"):
        with pytest.raises(ValidationError):
            validator.validate_python({**args, key: display[key]})
    prompt = definition.presentation.approval_prompt
    assert "{_library}" in prompt
    assert "{_target}" not in prompt
    if definition.name == "sharepoint_create_folder":
        assert "If no parent folder is chosen, use the root" in prompt
    elif definition.name == "sharepoint_write_file":
        assert "If no folder is chosen, use the root" in prompt
        assert "new file" in prompt and "No existing file is replaced" in prompt
    else:
        assert prompt.startswith("Replace this file")
        assert "A changed version stops the replacement" in prompt
