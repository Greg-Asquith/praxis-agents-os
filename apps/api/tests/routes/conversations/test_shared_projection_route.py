"""Verifies shared transcript HTTP bodies against persisted model messages."""

from base64 import b64encode
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from sqlalchemy import event

from models.agent import Agent
from models.agent_run import AgentRun
from services.agents.runtime.persistence import persist_new_messages
from tests.security.test_conversation_sharing import set_sharing, sharing_case

pytestmark = pytest.mark.asyncio
SECRET = "PRIVATE_HTTP_SENTINEL"


async def test_saved_tool_results_keep_the_normal_transcript_contract(db_session, db_async_client):
    case = await sharing_case(db_session)
    file_id = uuid4()
    await persist_new_messages(
        db_session,
        conversation=case.conversation,
        run_id=uuid4(),
        messages=[
            ModelRequest(
                parts=[
                    SystemPromptPart(SECRET),
                    UserPromptPart(
                        [
                            "Read this report",
                            BinaryContent(
                                data=SECRET.encode(),
                                media_type="application/pdf",
                                identifier=str(file_id),
                            ),
                        ]
                    ),
                ]
            ),
            ModelResponse(
                parts=[
                    ThinkingPart(SECRET),
                    TextPart("The result is ready."),
                    ToolCallPart("unknown_tool", {"query": "Quarterly results"}, "private-call"),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        "unknown_tool",
                        {"answer": "Saved tool result"},
                        "private-call",
                        metadata={"provider": SECRET},
                    ),
                    ToolReturnPart(
                        "run_workflow",
                        {"result": "Workflow complete"},
                        "workflow-call",
                        metadata={
                            "snapshot": SECRET,
                            "code_mode_trace": {
                                "output_excerpt": "Workflow complete",
                                "calls": [
                                    {
                                        "tool_name": "bigquery_run_query",
                                        "tool_call_id": "nested-call",
                                        "status": "succeeded",
                                        "args": SECRET,
                                        "presentation_result": {
                                            "rows": [{"quarter": "Autumn", "revenue": 99}],
                                        },
                                    },
                                    {
                                        "tool_name": "write_file",
                                        "tool_call_id": "pending-call",
                                        "status": "pending",
                                        "presentation_result": {"content": SECRET},
                                    },
                                ],
                            },
                        },
                    ),
                    ToolReturnPart(
                        "read_file",
                        {
                            "file_id": str(file_id),
                            "name": "Report.pdf",
                            "mode": "url",
                            "url": "https://example.com/report.pdf",
                        },
                        "file-call",
                    ),
                    ToolReturnPart(
                        "delegate_to_agent",
                        {
                            "status": "completed",
                            "output": "Specialist answer",
                            "conversation_id": str(uuid4()),
                            "run_id": str(uuid4()),
                        },
                        "specialist-call",
                    ),
                ]
            ),
        ],
        tool_approval_metadata_by_call_id={
            "private-call": {
                "effective_args": {"query": "Approved quarterly results"},
                "original_args": {"query": SECRET},
                "override_args": {"query": SECRET},
                "private_metadata": SECRET,
            }
        },
    )
    await db_session.commit()
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    path = f"/api/v1/conversations/{case.conversation.id}/messages"
    response = await db_async_client.get(path, headers=case.viewer_headers)
    assert response.status_code == 200, response.text
    assert SECRET not in response.text
    assert b64encode(SECRET.encode()).decode() not in response.text
    assert "PRIVATE_MESSAGE" not in response.text
    assert "Read this report" in response.text
    assert "The result is ready." in response.text
    assert "Specialist answer" in response.text
    assert "Autumn" in response.text
    assert str(file_id) in response.text
    assert "Saved tool result" in response.text
    assert response.json()["access"] == "viewer"
    completed_parts = [
        part
        for row in response.json()["messages"]
        for part in row["parts"]["parts"]
        if part.get("tool_call_id") == "private-call"
    ]
    assert len(completed_parts) == 2
    assert all(part["args"] == {"query": "Approved quarterly results"} for part in completed_parts)
    for row in response.json()["messages"]:
        assert set(row) == {
            "id",
            "conversation_id",
            "role",
            "sequence",
            "created_at",
            "updated_at",
            "parts",
            "metadata",
            "error",
            "tool_name",
            "client_message_id",
        }
        assert row["error"] is None
        assert row["client_message_id"] is None
    owner = await db_async_client.get(path, headers=case.owner_headers)
    assert owner.status_code == 200
    assert SECRET in owner.text
    assert owner.json()["access"] == "owner"


@pytest.mark.parametrize("view", ["workspace_shared"])
async def test_viewer_status_reads_do_not_load_executable_run_state(
    db_session, db_async_client, view
):
    case = await sharing_case(db_session)
    agent = Agent(
        name="Sharing status test",
        slug=f"status-{uuid4().hex}",
        instructions="Test",
        workspace_id=case.workspace.id,
        created_by=case.owner.id,
    )
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        AgentRun(
            conversation_id=case.conversation.id,
            agent_id=agent.id,
            workspace_id=case.workspace.id,
            user_id=case.owner.id,
            trigger="interactive",
            status="awaiting_approval",
            metadata_json={"approval_state": {"credentials": SECRET}},
            error_message=SECRET,
            usage_json={"provider": SECRET},
            completion_json={"internal": SECRET},
        )
    )
    await db_session.commit()
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "agent_runs" in statement:
            statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        path = (
            f"/api/v1/conversations/{case.conversation.id}"
            if view == "detail"
            else "/api/v1/conversations/?scope=workspace_shared"
        )
        response = await db_async_client.get(path, headers=case.viewer_headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    body = response.json()
    conversation = body if view == "detail" else body["conversations"][0]
    assert conversation["active_run_status"] == "awaiting_approval"
    assert SECRET not in response.text
    assert statements, "The persisted run status must be read from the database."
    for statement in statements:
        assert "agent_runs.status" in statement
        for column in ("metadata", "usage_json", "completion_json", "error_message"):
            assert f"agent_runs.{column}" not in statement
