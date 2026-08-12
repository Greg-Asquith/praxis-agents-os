# apps/api/integrations/gmail/tools/read_message.py

"""Read Gmail message runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

from integrations.gmail.references import GmailMessageReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.read_message import read_message
from .schemas import GmailReadOutput
from .utils import (
    GMAIL_BINDING,
    RESULTS_FIELD,
    gmail_available,
    gmail_client,
)


async def gmail_read_message(
    ctx: RunContext[RuntimeDeps],
    message_id: Annotated[
        GmailMessageReference,
        Field(description="Scoped Gmail message reference returned by search."),
    ],
) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry, references) -> Any:
        reference = references[0]

        async def execute() -> Any:
            client = await gmail_client(ctx, entry)
            result = await read_message(client, message_id=reference.external_id)
            return IntegrationAuditOutcome(result, external_ref=reference.external_id)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="gmail_read_message",
            operation="read_message",
            execute=execute,
        )

    results = await run_context_targets(
        ctx,
        binding=GMAIL_BINDING,
        references=[message_id],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="gmail_read_message",
    function=gmail_read_message,
    description="Read one Gmail message by id from the active mailbox context.",
    provider="gmail",
    label="Read Gmail Message",
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GmailReadOutput,
    integration_binding=GMAIL_BINDING,
    availability_check=gmail_available,
    presentation=ToolPresentation(
        icon="gmail",
        running_label="Reading Gmail Message",
        completed_label="Read Gmail Message",
        failed_label="Couldn't Read Gmail Message",
        arg_fields=(
            ToolFieldPresentation(
                key="message_id",
                label="Message",
                format="entity",
                editable=True,
                entity_kind="gmail_message",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
