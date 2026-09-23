# apps/api/services/integrations/report_results.py

"""Shared retrieval guidance for structured integration reports."""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic_core import to_jsonable_python

from core.exceptions.integration import IntegrationReportTooLargeError
from services.files.contract import tool_result_max_size_bytes


def report_result_max_bytes() -> int:
    """Use the retained JSON File limit for complete report retrieval."""
    return tool_result_max_size_bytes()


@dataclass
class ReportResultBudget:
    """Bound the combined response pages without discarding report rows."""

    provider_key: str
    operation: str
    maximum: int = field(default_factory=report_result_max_bytes)
    used: int = 0

    @property
    def remaining(self) -> int:
        self._check(self.used + 1)
        return self.maximum - self.used

    def add(self, value: Any, *, extra_bytes: int = 0) -> None:
        size = len(
            json.dumps(
                to_jsonable_python(value), ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        self._check(self.used + size + extra_bytes)
        self.used += size + extra_bytes

    def _check(self, size: int) -> None:
        if size > self.maximum:
            raise IntegrationReportTooLargeError(
                "The report exceeds the file size limit. No partial report was returned. "
                "Request fewer fields or a shorter date range.",
                provider_key=self.provider_key,
                operation=self.operation,
            )


REPORT_RESULT_GUIDANCE = (
    " When the result contains preview=true, use data to inspect row structure and provider "
    "metadata, then read file_reference for the full saved rows needed by your task. "
    "Call read_file with file_id=file_reference and offset to inspect saved rows. "
    "For filtering, aggregation, or whole-report calculations, call run_code with "
    "file_ids=[file_reference] when available. Choose an available OpenAI or Anthropic helper "
    "for files above Google's inline-text limit. Never calculate whole-report totals from "
    "preview rows. Do not repeat or split queries to recover rows already saved. "
    "Use each lists entry's total as its saved list length; do not fetch more source data "
    "because its shown count is smaller. Request further provider pages only when the provider's "
    "truncated or pagination metadata indicates missing source rows. If you cannot read or "
    "process the saved result, report that limitation instead of refetching it."
)
