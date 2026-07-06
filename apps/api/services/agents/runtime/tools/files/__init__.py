# apps/api/services/agents/runtime/tools/files/__init__.py

"""Runtime file and scratch tools.

Pydantic AI 2.1.0 probe findings used by this package:
- ``ApprovalRequired(metadata: dict[str, Any] | None = None)`` can be raised
  conditionally from a tool body, and ``RunContext.tool_call_approved`` is true
  on approved replay.
- ``ToolReturn`` accepts ``return_value``, rich ``content``, and metadata.
- ``BinaryContent`` is a dataclass constructed with ``data``, ``media_type``,
  ``identifier``, and optional ``vendor_metadata``; its stored field is
  ``_identifier``.
"""

from services.agents.runtime.tools.files.list_files import (
    ListFilesOutput,
    RuntimeFileSummary,
    RuntimeScratchSummary,
    list_files,
)
from services.agents.runtime.tools.files.promote_scratch import (
    PromoteScratchOutput,
    promote_scratch,
)
from services.agents.runtime.tools.files.read_file import read_file
from services.agents.runtime.tools.files.write_file import WriteFileOutput, write_file

__all__ = [
    "ListFilesOutput",
    "PromoteScratchOutput",
    "RuntimeFileSummary",
    "RuntimeScratchSummary",
    "WriteFileOutput",
    "list_files",
    "promote_scratch",
    "read_file",
    "write_file",
]
