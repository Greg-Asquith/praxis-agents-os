"""Run outcomes stay bounded to the authorised transcript page."""

from uuid import uuid4

import pytest
from sqlalchemy import event

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from tests.security.test_conversation_sharing import set_sharing, sharing_case


@pytest.mark.parametrize("viewer", [False, True])
async def test_message_runs_are_page_bounded_and_keep_viewer_filtering(
    db_session, db_async_client, viewer
):
    case = await sharing_case(db_session)
    agent = Agent(
        name="Transcript test",
        slug=f"transcript-{uuid4().hex}",
        instructions="Test",
        workspace_id=case.workspace.id,
        created_by=case.owner.id,
    )
    other_conversation = Conversation(
        user_id=case.owner.id,
        workspace_id=case.workspace.id,
        created_by=case.owner.id,
    )
    db_session.add_all([agent, other_conversation])
    await db_session.flush()
    runs = [
        AgentRun(
            conversation_id=conversation_id,
            agent_id=agent.id,
            workspace_id=case.workspace.id,
            user_id=case.owner.id,
            trigger="interactive",
            status="failed",
            outcome="budget_exhausted",
            error_code="usage_limit_exceeded",
            error_message="The run reached its limit.",
            metadata_json={"approval_state": "PRIVATE_RUN_STATE"},
            usage_json={"provider": "PRIVATE_USAGE_STATE"},
            deleted=deleted,
        )
        for conversation_id, deleted in [
            (case.conversation.id, False),
            (case.conversation.id, False),
            (other_conversation.id, False),
            (case.conversation.id, True),
        ]
    ]
    db_session.add_all(runs)
    await db_session.flush()
    for sequence, run_id in enumerate(
        [
            str(runs[1].id),
            str(runs[0].id),
            str(runs[0].id),
            str(runs[2].id),
            str(runs[3].id),
            str(uuid4()),
            "invalid-run-id",
        ],
        start=6,
    ):
        db_session.add(
            ConversationMessage(
                conversation_id=case.conversation.id,
                workspace_id=case.workspace.id,
                role="assistant",
                sequence=sequence,
                metadata_json={"agent_run_id": run_id},
                parts={
                    "parts": [
                        {
                            "part_kind": "tool-call",
                            "tool_name": "write_file",
                            "tool_call_id": f"call-{sequence}",
                            "args": {"content": "Unfinished"},
                        }
                    ]
                },
            )
        )
    await db_session.commit()
    if viewer:
        assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    headers = case.viewer_headers if viewer else case.owner_headers
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM agent_runs" in statement:
            statements.append((statement, parameters))

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await db_async_client.get(
            f"/api/v1/conversations/{case.conversation.id}/messages?limit=6",
            headers=headers,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body["runs"]) == [str(runs[0].id)]
    assert body["runs"][str(runs[0].id)]["error_message"] == "The run reached its limit."
    assert body["runs"][str(runs[0].id)]["outcome"] == "budget_exhausted"
    assert "PRIVATE_RUN_STATE" not in response.text
    assert "PRIVATE_USAGE_STATE" not in response.text
    assert len(statements) == 1
    statement, parameters = statements[0]
    assert "agent_runs.id IN" in statement
    assert runs[1].id not in parameters
    assert body["has_more"] is True
    assert [row["sequence"] for row in body["messages"]] == list(range(7, 13))
    assert all(bool(row["parts"]["parts"]) is not viewer for row in body["messages"])
    previous = await db_async_client.get(
        f"/api/v1/conversations/{case.conversation.id}/messages?limit=1&before_sequence=7",
        headers=headers,
    )
    assert previous.status_code == 200, previous.text
    assert list(previous.json()["runs"]) == [str(runs[1].id)]
    empty = await db_async_client.get(
        f"/api/v1/conversations/{case.conversation.id}/messages?before_sequence=1",
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json()["runs"] == {}
