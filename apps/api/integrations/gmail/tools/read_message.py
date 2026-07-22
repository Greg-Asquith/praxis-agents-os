# apps/api/integrations/gmail/tools/read_message.py

"""Read Gmail message runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out

from ..operations.read_message import read_message
from .schemas import GmailReadOutput
from .utils import (
    GMAIL_BINDING,
    RESULTS_FIELD,
    fan_out_dict,
    gmail_available,
    gmail_client,
    run_audited_operation,
)


async def gmail_read_message(
    ctx: RunContext[RuntimeDeps],
    message_id: Annotated[str, Field(description="Gmail message id returned by search.")],
) -> dict[str, Any]:
    normalized_id = message_id.strip()
    if not normalized_id:
        raise ModelRetry("gmail_read_message requires a non-empty message_id.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await gmail_client(ctx, entry)
            return await read_message(client, message_id=normalized_id)

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="gmail_read_message",
            operation="read_message",
            execute=execute,
            external_ref=normalized_id,
        )

    results = await run_context_fan_out(
        ctx.deps,
        binding=GMAIL_BINDING,
        operation=operation,
    )
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="gmail_read_message",
    function=gmail_read_message,
    description="Read one Gmail message by id from the active mailbox context.",
    provider="gmail",
    label="Read Gmail Message",
    effect=TOOL_EFFECT_READ,
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
        arg_fields=(ToolFieldPresentation(key="message_id", label="Message"),),
        result_fields=RESULTS_FIELD,
    ),
)
