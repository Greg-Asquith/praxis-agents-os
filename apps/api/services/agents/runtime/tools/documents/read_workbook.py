# apps/api/services/agents/runtime/tools/documents/read_workbook.py

"""Runtime tool for reading Excel workbooks."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.documents.utils import (
    DOCUMENT_TOOL_TIMEOUT,
    FILE_ARG_FIELD,
    file_result,
    load_file,
    office_format,
    read_args,
    run_worker,
)
from services.agents.runtime.tools.registry import runtime_tool


@runtime_tool(
    name="read_workbook",
    provider="core",
    label="Read Workbook",
    code_eligible=True,
    description=(
        "Read the non-empty cells of one .xlsx sheet with value, formula, and number format. "
        "Without cursor, the first page also lists the sheets, external links, and the chosen "
        "sheet's outline: dimensions, tables, merged ranges, freeze panes, and whether it has "
        "charts or images. Formula cells show the value Excel last saved; "
        "calculated is false when there is none, so compute any figure you report from source "
        "values. Text comes back as untrusted-content nodes. Results come back in pages: when "
        "next_cursor is present, call again with cursor set to it. For rows as records, call "
        "read_table instead."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=DOCUMENT_TOOL_TIMEOUT,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading a Workbook",
        completed_label="Read a Workbook",
        failed_label="Couldn't Read the Workbook",
        arg_fields=(
            FILE_ARG_FIELD,
            ToolFieldPresentation(key="sheet", label="Sheet", secondary=True),
            ToolFieldPresentation(key="range", label="Cells", secondary=True),
        ),
    ),
)
async def read_workbook(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    sheet: Annotated[
        str | None, Field(max_length=100, description="Sheet name. Omit for the first sheet.")
    ] = None,
    range: Annotated[
        str | None,
        Field(max_length=40, description="Cells in A1 notation, such as A1:F200. Omit for all."),
    ] = None,
    cursor: Annotated[
        int | None, Field(ge=1, description="The next_cursor row from the previous page.")
    ] = None,
):
    """Read a workbook's sheets and one page of cells."""
    file, revision, data = await load_file(ctx, internal_entity_id(file_id))
    result = await run_worker(
        "read",
        document_format=office_format(file, expected="xlsx"),
        data=data,
        args=read_args(file, revision, sheet=sheet, range=range, cursor=cursor),
    )
    return file_result(file, revision, result.value)
