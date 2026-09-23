# apps/api/services/integrations/context/execution.py

"""Shared authorization and failure isolation for context operations."""

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from core.exceptions.integration import (
    IntegrationError,
    IntegrationReportTooLargeError,
    IntegrationUnverifiedMutationError,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import (
    IntegrationContextResult,
    serialize_fan_out_results,
)
from services.integrations.context.utils import sanitize_context_error
from services.integrations.report_results import ReportResultBudget
from services.integrations.utils import integration_failure_code

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.tools.contract import IntegrationToolBinding


async def _run_authorized_entries[T](
    ctx: "RunContext[RuntimeDeps]",
    *,
    binding: "IntegrationToolBinding",
    selected: Sequence[tuple[ResolvedContextEntry, T]],
    operation: Callable[[ResolvedContextEntry, T], Awaitable[Any]],
    result_budget: ReportResultBudget | None = None,
) -> list[IntegrationContextResult]:
    """Execute selected entries with one authorization and isolation loop."""
    from services.integrations.operations import _resolve_dispatched_integration_definition

    definition = _resolve_dispatched_integration_definition(ctx)
    if definition.integration_binding != binding:
        raise RuntimeError("Context binding does not match the dispatched integration tool")

    results: list[IntegrationContextResult] = []

    def append_result(result: IntegrationContextResult) -> None:
        if result_budget is not None:
            result_budget.add(
                serialize_fan_out_results([result])[0], extra_bytes=int(bool(results))
            )
        results.append(result)

    for entry, operation_input in selected:
        if binding.requires_write and not entry.write_allowed:
            from services.integrations.operations import record_integration_write_denial

            await record_integration_write_denial(ctx, entry)
            append_result(
                IntegrationContextResult(
                    entry=entry,
                    status="error",
                    error_code="write_not_permitted",
                    error_message="This resource does not permit writes.",
                )
            )
            continue
        try:
            data = await operation(entry, operation_input)
        except IntegrationReportTooLargeError:
            raise
        except Exception as exc:
            append_result(
                IntegrationContextResult(
                    entry=entry,
                    status="error",
                    data=(
                        exc.result_data
                        if isinstance(exc, IntegrationUnverifiedMutationError)
                        else None
                    ),
                    error_code=integration_failure_code(exc),
                    error_message=sanitize_context_error(
                        exc.user_message if isinstance(exc, IntegrationError) else str(exc)
                    ),
                )
            )
        else:
            append_result(IntegrationContextResult(entry=entry, status="success", data=data))
    return results
