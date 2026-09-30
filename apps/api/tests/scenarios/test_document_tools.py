"""Workflows total saved reports and update workbooks through document tools, with no provider sandbox."""

import json
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

from core.database import set_session_tenant_context
from core.settings import settings
from models.workspace import Workspace
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME
from services.documents.worker import close_document_worker_pool
from services.files.create_conversation_file_references import create_conversation_file_references
from services.files.create_file_with_revision import create_file_with_revision
from services.files.revision_actor import FileRevisionActor
from tests.support.office_documents import sales_workbook
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    resume_code_mode_scenario,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

_ROWS = 1_500
_TOTAL_SCRIPT = """
reference = {reference!r}
total = 0
count = 0
offset = 0
while True:
    page = await read_table(
        file_id=reference, list_name="results.0.data.rows", offset=offset, limit=1000
    )
    for row in page["rows"]:
        total += row["clicks"]
        count += 1
    if "next_offset" not in page:
        break
    offset = page["next_offset"]
{{"total": total, "count": count, "total_rows": page["total_rows"]}}
"""

_WORKBOOK_SCRIPT = """
reference = {reference!r}
page = await read_table(file_id=reference, sheet="Sales", range="A1:B31")
total = 0
for row in page["rows"]:
    total += row["Amount"]
saved = await edit_workbook(
    file_id=reference,
    base_revision_id=page["revision_id"],
    operations=[
        {{"op": "set_cells", "sheet": "Sales", "anchor": "D2", "values": [[total], ["=SUM(B2:B31)"]]}}
    ],
)
cells = {{}}
for block in saved["readback"]["blocks"]:
    for cell in block["cells"]:
        cells[cell["ref"]] = cell
if cells["D2"]["value"] != total:
    raise ValueError("The written total didn't read back")
{{
    "total": total,
    "formula_calculated": cells["D3"]["calculated"],
    "revision_number": saved["revision_number"],
}}
"""


@pytest.fixture
def report_storage(monkeypatch, tmp_path) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    yield
    reset_storage_provider_cache()


@pytest_asyncio.fixture
async def document_workers() -> AsyncIterator[None]:
    yield
    await close_document_worker_pool()


async def test_workflow_pages_a_saved_report_and_totals_every_row(
    db_session_factory, report_storage, document_workers
):
    context = await build_scenario_agent(db_session_factory)
    report = {
        "results": [
            {
                "status": "ok",
                "data": {
                    "rows": [
                        {"term": f"search term {index}", "clicks": index} for index in range(_ROWS)
                    ]
                },
            }
        ]
    }
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        saved = await create_file_with_revision(
            db,
            workspace=await db.get(Workspace, context.workspace_id),
            name="google_ads_run_report.json",
            content=json.dumps(report).encode(),
            content_type="application/json",
            extension=".json",
            actor=FileRevisionActor(agent_id=context.agent_id),
        )
        saved.file.is_tool_result = True
        await create_conversation_file_references(
            db,
            workspace_id=context.workspace_id,
            conversation_id=context.conversation_id,
            file_ids=[saved.file.id],
            created_by_user_id=context.user_id,
        )
        await db.commit()
    reference = {"entity_id": str(saved.file.id), "label": saved.file.name}
    script = _TOTAL_SCRIPT.format(reference=reference)

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall(RUN_WORKFLOW_TOOL_NAME, {"code": script}, "total"),)),
                "Every row is counted.",
            ]
        ),
    )

    assert result.run.status == "completed"
    [workflow] = result.tool_returns(RUN_WORKFLOW_TOOL_NAME)
    # Row text is untrusted, so the whole workflow value comes back framed.
    content = workflow["content"]
    assert content["node"] == "praxis_untrusted"
    assert json.loads(content["content"]) == {
        "total": sum(range(_ROWS)),
        "count": _ROWS,
        "total_rows": _ROWS,
    }
    pages = [row for row in result.audit_rows if row.tool_name == "read_table"]
    assert len(pages) > 1


async def test_workflow_writes_a_workbook_total_and_checks_the_read_back(
    db_session_factory, report_storage, document_workers
):
    context = await build_scenario_agent(db_session_factory)
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        saved = await create_file_with_revision(
            db,
            workspace=await db.get(Workspace, context.workspace_id),
            name="sales.xlsx",
            content=sales_workbook(rows=30),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            extension=".xlsx",
            actor=FileRevisionActor(user_id=context.user_id),
        )
        await db.commit()
    reference = {"entity_id": str(saved.file.id), "label": saved.file.name}

    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": _WORKBOOK_SCRIPT.format(reference=reference)},
                        "total",
                    ),
                )
            ),
            "The total is written.",
        ]
    )

    # The script read file text, so the write waits for approval rather than running unattended.
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    result = await resume_code_mode_scenario(
        db_session_factory, context, suspended=suspended, model=model
    )

    assert result.run.status == "completed"
    [workflow] = result.tool_returns(RUN_WORKFLOW_TOOL_NAME)
    assert json.loads(workflow["content"]["content"]) == {
        "total": sum(range(1, 31)),
        "formula_calculated": False,
        "revision_number": 2,
    }
