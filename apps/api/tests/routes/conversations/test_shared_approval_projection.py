"""Checks performed arguments across persisted shared transcript pages."""

from uuid import uuid4

from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from services.agents.runtime.approval_events import build_deferred_tool_result_metadata
from services.agents.runtime.persistence import persist_new_messages
from tests.security.test_conversation_sharing import set_sharing, sharing_case


async def test_shared_pages_resolve_approved_arguments_by_run_and_call(db_session, db_async_client):
    case = await sharing_case(db_session)
    runs = [uuid4(), uuid4()]
    saved = []
    for index, run_id in enumerate(runs):
        call = ModelResponse(
            parts=[ToolCallPart("example_tool", {"value": "ORIGINAL_SECRET"}, "same-call")]
        )
        result = ModelRequest(parts=[ToolReturnPart("example_tool", "Done", "same-call")])
        approval_metadata = build_deferred_tool_result_metadata(
            message_history=[call],
            new_messages=[result],
            deferred_tool_results=DeferredToolResults(
                approvals={"same-call": ToolApproved(override_args={"value": f"approved-{index}"})}
            ),
        )
        approval_metadata["same-call"]["unrelated"] = "PRIVATE_METADATA"
        saved.extend(
            await persist_new_messages(
                db_session,
                conversation=case.conversation,
                run_id=run_id,
                messages=[call, result],
                tool_approval_metadata_by_call_id=approval_metadata,
            )
        )
    pending = await persist_new_messages(
        db_session,
        conversation=case.conversation,
        run_id=uuid4(),
        messages=[
            ModelResponse(
                parts=[ToolCallPart("example_tool", {"value": "PENDING_SECRET"}, "same-call")]
            )
        ],
    )
    await db_session.commit()
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    path = f"/api/v1/conversations/{case.conversation.id}/messages"
    for index, row in enumerate(saved):
        params = {"limit": 1, "before_sequence": row.sequence + 1}
        viewer = await db_async_client.get(path, headers=case.viewer_headers, params=params)
        owner = await db_async_client.get(path, headers=case.owner_headers, params=params)
        assert viewer.status_code == owner.status_code == 200
        [projected] = viewer.json()["messages"]
        [original] = owner.json()["messages"]
        assert projected["parts"]["parts"][0]["args"] == {"value": f"approved-{index // 2}"}
        assert projected["metadata"] == {"agent_run_id": str(runs[index // 2])}
        assert "ORIGINAL_SECRET" not in viewer.text
        assert "PRIVATE_METADATA" not in viewer.text
        if index % 2:
            assert (
                original["metadata"]["approval_results"]["same-call"]["effective_args"]
                == projected["parts"]["parts"][0]["args"]
            )
        else:
            assert original["parts"]["parts"][0]["args"] == {"value": "ORIGINAL_SECRET"}
    response = await db_async_client.get(path, headers=case.viewer_headers, params={"limit": 1})
    assert response.json()["messages"][0]["sequence"] == pending[0].sequence
    assert response.json()["messages"][0]["parts"] == {"parts": []}
    assert "PENDING_SECRET" not in response.text
    assert response.json()["has_more"] is True
