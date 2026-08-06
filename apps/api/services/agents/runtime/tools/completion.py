# apps/api/services/agents/runtime/tools/completion.py

"""Completion-report tool for contract-bound unattended runs."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints
from pydantic_ai import ModelRetry, RunContext

from services.agent_runs.domain import RUN_TRIGGER_SCHEDULED
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import TOOL_EFFECT_WRITE, ToolPresentation
from services.agents.runtime.tools.registry import runtime_tool
from services.completion_contract import (
    MAX_COMPLETION_JSON_BYTES,
    REPORT_COMPLETION_TOOL_NAME,
    completion_contract_from_run_metadata,
    validate_completion_json,
)

CompletionStatus = Literal["pass", "fail"]
CompletionEvidence = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


@runtime_tool(
    name=REPORT_COMPLETION_TOOL_NAME,
    provider="core",
    label="Report Completion",
    description=(
        "File the required verdict for this unattended run. Use pass only when every "
        "declared completion criterion is satisfied; otherwise use fail. "
        f"The complete report must fit within {MAX_COMPLETION_JSON_BYTES} serialized bytes."
    ),
    effect=TOOL_EFFECT_WRITE,
    supports_approval=False,
    takes_ctx=True,
    timeout=5,
    configurable=False,
    always_allowed_when_mounted=True,
    presentation=ToolPresentation(
        icon="list-todo",
        running_label="Checking Completion",
        completed_label="Reported Completion",
        failed_label="Couldn't Report Completion",
    ),
)
async def report_completion(
    ctx: RunContext[RuntimeDeps],
    status: CompletionStatus,
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ],
    evidence: Annotated[list[CompletionEvidence], Field(max_length=20)],
) -> dict[str, object]:
    """Persist bounded completion evidence for finalization to interpret."""
    contract = completion_contract_from_run_metadata(ctx.deps.run.metadata_json)
    if ctx.deps.run.trigger != RUN_TRIGGER_SCHEDULED or contract is None or not contract.required:
        raise ModelRetry("This run does not require a completion report.")
    if ctx.deps.run.completion_json is not None:
        raise ModelRetry(
            "A completion report has already been filed; the first accepted report is authoritative."
        )

    report: dict[str, object] = {
        "status": status,
        "summary": summary,
        "evidence": evidence,
    }
    ctx.deps.run.completion_json = validate_completion_json(report)
    await ctx.deps.db.flush()
    return report
