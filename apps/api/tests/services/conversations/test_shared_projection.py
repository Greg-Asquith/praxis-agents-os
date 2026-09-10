"""Checks ordinary shared transcript rendering and approval boundaries."""

from datetime import UTC, datetime
from uuid import uuid4

from models.conversation import ConversationMessage
from services.conversations.shared_projection import project_shared_message

SECRET = "PRIVATE_SENTINEL"


def message(parts, *, role="assistant", sequence=1, run_id="run"):
    return ConversationMessage(
        id=uuid4(),
        conversation_id=uuid4(),
        workspace_id=uuid4(),
        role=role,
        parts={"parts": parts, "provider_metadata": SECRET},
        metadata_json={"agent_run_id": run_id, "approval_results": SECRET},
        error_json={"message": SECRET},
        sequence=sequence,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def result(name, content, **kwargs):
    return {
        "part_kind": "tool-return",
        "tool_name": name,
        "tool_call_id": "call",
        "content": content,
        **kwargs,
    }


def test_normal_completed_tool_contract_is_preserved():
    content = {"rows": [{"name": "Report", "value": 2}], "metadata": {"currency": "GBP"}}
    parts = [
        {
            "part_kind": "tool-call",
            "tool_name": "example_tool",
            "tool_call_id": "call",
            "args": {"query": "report"},
        },
        result("example_tool", content, metadata={"public_result": content}),
        {"part_kind": "text", "content": "Here is your report."},
    ]
    projected = project_shared_message(message(parts))
    assert projected.parts["parts"][0] == parts[0]
    assert projected.parts["parts"][1] == {**parts[1], "args": {"query": "report"}}
    assert projected.parts["parts"][2] == parts[2]
    assert projected.metadata_json == {"agent_run_id": "run"}
    assert projected.error_json is None


def test_model_and_approval_metadata_are_not_transcript_content():
    row = message(
        [
            {"part_kind": "system-prompt", "content": SECRET},
            {"part_kind": "thinking", "content": SECRET},
            {
                "part_kind": "tool-call",
                "tool_name": "example_tool",
                "status": "awaiting_approval",
                "args": {"secret": SECRET},
            },
            {"part_kind": "text", "content": "Saved answer", "provider_metadata": SECRET},
        ]
    )
    projected = project_shared_message(row)
    assert projected.parts == {"parts": [{"part_kind": "text", "content": "Saved answer"}]}
    assert SECRET not in projected.model_dump_json()
    assert project_shared_message(message(row.parts["parts"], role="system")).parts == {"parts": []}


def test_workflow_preserves_completed_result_and_hides_pending_approval():
    completed = {
        "tool_call_id": "done",
        "tool_name": "example",
        "status": "succeeded",
        "presentation_result": {"count": 2},
    }
    pending = {
        "tool_call_id": "pending",
        "tool_name": "example",
        "status": "pending",
        "presentation_result": SECRET,
    }
    projected = project_shared_message(
        message(
            [
                result(
                    "run_workflow",
                    "Done",
                    metadata={
                        "code_mode_trace": {"calls": [completed, pending], "snapshot": SECRET},
                        "approval": SECRET,
                    },
                )
            ]
        )
    )
    trace = projected.parts["parts"][0]["metadata"]["code_mode_trace"]
    assert trace["calls"] == [completed]
    assert SECRET not in projected.model_dump_json()


def test_attachment_keeps_existing_reference_without_binary_bytes():
    file_id = str(uuid4())
    projected = project_shared_message(
        message(
            [
                {
                    "part_kind": "user-prompt",
                    "content": [
                        "Read this",
                        {
                            "kind": "binary",
                            "identifier": file_id,
                            "media_type": "application/pdf",
                            "data": SECRET,
                        },
                    ],
                }
            ]
        )
    )
    assert projected.parts["parts"][0]["content"][1] == {
        "kind": "binary",
        "identifier": file_id,
        "media_type": "application/pdf",
    }
    assert SECRET not in projected.model_dump_json()


def test_pending_call_is_hidden_until_same_run_result_exists():
    call = {
        "part_kind": "tool-call",
        "tool_name": "example_tool",
        "tool_call_id": "call",
        "args": {"query": "report"},
    }
    row = message([call])
    assert project_shared_message(row).parts == {"parts": []}
    assert project_shared_message(row, completed_calls={("other-run", "call"): None}).parts == {
        "parts": []
    }
    assert project_shared_message(
        row, completed_calls={("run", "call"): {"query": "report"}}
    ).parts == {"parts": [call]}


def test_explicit_null_effective_args_replace_original_proposal():
    row = message(
        [
            {
                "part_kind": "tool-call",
                "tool_name": "example_tool",
                "tool_call_id": "call",
                "args": {"secret": SECRET},
            },
            result("example_tool", "Done"),
        ]
    )
    row.metadata_json["approval_results"] = {"call": {"effective_args": None}}
    projected = project_shared_message(row)
    assert all(part["args"] is None for part in projected.parts["parts"])
    assert SECRET not in projected.model_dump_json()
