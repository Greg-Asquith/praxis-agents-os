# apps/api/services/agents/runtime/tools/documents/read_table.py

"""Runtime tool for reading rows from workbooks, CSV files, and saved results."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from models.files import File, FileRevision
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
    OFFICE_EXTENSIONS,
    file_result,
    load_file,
    read_args,
    run_worker,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.documents.reading import DEFAULT_TABLE_ROWS, MAX_TABLE_ROWS

_TABLE_EXTENSIONS = {".csv": "csv", ".tsv": "tsv", ".json": "json"}


@runtime_tool(
    name="read_table",
    provider="core",
    label="Read Table",
    code_eligible=True,
    description=(
        "Read rows as records from an .xlsx sheet, a CSV file, or a saved tool result. For a "
        "saved result, pass the file_reference from its preview and list_name from its lists. "
        "Returns columns, rows as dictionaries, and total_rows. Numbers stay numbers; text "
        "comes back as untrusted-content nodes. A workbook formula Excel never calculated "
        "comes back as None and its cell is listed in uncalculated_cells; don't treat it as "
        "zero. When next_offset is present, call again with offset set to it. Inside "
        "run_code, page through every row and compute totals there, never from a preview."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=DOCUMENT_TOOL_TIMEOUT,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading a Table",
        completed_label="Read {total_rows} Rows",
        failed_label="Couldn't Read the Table",
        arg_fields=(
            FILE_ARG_FIELD,
            ToolFieldPresentation(key="sheet", label="Sheet", secondary=True),
            ToolFieldPresentation(key="list_name", label="List", secondary=True),
        ),
    ),
)
async def read_table(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    sheet: Annotated[
        str | None, Field(max_length=100, description="Workbook sheet name. Omit for the first.")
    ] = None,
    range: Annotated[
        str | None,
        Field(
            max_length=40, description="Workbook cells in A1 notation; the first row is the header."
        ),
    ] = None,
    list_name: Annotated[
        str | None,
        Field(
            max_length=200, description="For a saved result, the name of one entry in its lists."
        ),
    ] = None,
    offset: Annotated[int, Field(ge=0, description="Rows to skip after the header.")] = 0,
    limit: Annotated[
        int, Field(ge=1, le=MAX_TABLE_ROWS, description="Most rows to return.")
    ] = DEFAULT_TABLE_ROWS,
):
    """Read one page of rows from a table-shaped File."""
    file, revision, document_format, data = await load_file(
        ctx, internal_entity_id(file_id), _table_format
    )
    args = read_args(file, revision, sheet=sheet, range=range, offset=offset, limit=limit)
    if document_format == "json":
        args |= {"list_name": list_name, "retained": _is_retained_result(file, revision)}
    result = await run_worker("read_table", document_format=document_format, data=data, args=args)
    return file_result(file, revision, result.value)


def _table_format(file: File) -> str:
    extension = (file.extension or "").lower()
    if OFFICE_EXTENSIONS.get(extension) == "xlsx":
        return "xlsx"
    if extension in _TABLE_EXTENSIONS:
        return _TABLE_EXTENSIONS[extension]
    raise ModelRetry("read_table reads .xlsx, CSV, TSV, and saved result files.")


def _is_retained_result(file: File, revision: FileRevision) -> bool:
    # Only the revision the runtime saved holds server-framed nodes; later revisions are edits.
    return bool(file.is_tool_result) and revision.revision_number == 1
