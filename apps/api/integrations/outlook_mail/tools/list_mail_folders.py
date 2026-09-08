# apps/api/integrations/outlook_mail/tools/list_mail_folders.py

"""Lists folders in the selected Outlook mailboxes."""

from urllib.parse import quote

from pydantic_ai import RunContext

from core.exceptions.integration import IntegrationNotFoundError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolPresentation,
)
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_mail_folders import list_mail_folders
from ..operations.utils import WELL_KNOWN_FOLDERS, text, untrusted
from .schemas import FoldersOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    mailbox_time_zone,
    outlook_mail_available,
)


async def outlook_mail_list_folders(ctx: RunContext[RuntimeDeps]) -> dict:
    async def operation(entry):
        async def execute():
            client = await mailbox_client(ctx, entry)
            folders = await list_mail_folders(client)
            known_ids = {}
            for name in sorted(WELL_KNOWN_FOLDERS):
                try:
                    folder = await client.get(
                        f"/me/mailFolders/{quote(name, safe='')}",
                        operation="list_mail_folders",
                        policy=IntegrationRequestPolicy.READ,
                        params={"$select": "id"},
                    )
                except IntegrationNotFoundError:
                    continue
                if isinstance(folder, dict) and isinstance(folder.get("id"), str):
                    known_ids[folder["id"]] = name
            return IntegrationAuditOutcome(
                {
                    "folders": [
                        {
                            "name": untrusted(
                                text(folder.get("id"), 512), text(folder.get("displayName"))
                            ),
                            "well_known_name": known_ids.get(folder.get("id")),
                            "unread_count": folder.get("unreadItemCount", 0),
                            "total_count": folder.get("totalItemCount", 0),
                            "child_folder_count": folder.get("childFolderCount", 0),
                        }
                        for folder in folders
                    ],
                    "mailbox_time_zone": mailbox_time_zone(entry),
                }
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_list_folders",
            operation="list_mail_folders",
            execute=execute,
        )

    return bounded_output(
        await run_context_fan_out(ctx, binding=OUTLOOK_MAIL_BINDING, operation=operation)
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_list_folders",
    function=outlook_mail_list_folders,
    description=(
        "Lists up to 200 top-level folders in each selected Outlook mailbox, including message "
        "and unread counts."
    ),
    provider="outlook_mail",
    label="List Outlook folders",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=FoldersOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Listing Outlook folders",
        completed_label="Listed Outlook folders",
        failed_label="Could not list Outlook folders",
        result_fields=RESULTS_FIELD,
    ),
)
