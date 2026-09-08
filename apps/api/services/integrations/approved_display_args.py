# apps/api/services/integrations/approved_display_args.py

"""Returns server-retained presentation evidence for the approved tool call."""

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.approval import code_mode_nested_call
from services.agents.runtime.context import RuntimeDeps


def approved_display_args(ctx: RunContext[RuntimeDeps]) -> dict:
    """Loads evidence by run and call identity, never from replay arguments."""
    if ctx.tool_call_approved:
        requests = load_suspended_run_state(ctx.deps.run).deferred_tool_requests
        for approval in requests.approvals:
            metadata = (requests.metadata or {}).get(approval.tool_call_id, {})
            call = code_mode_nested_call(metadata) or approval
            if call.tool_call_id == ctx.tool_call_id and call.tool_name == ctx.tool_name:
                display = metadata.get("display_args")
                if isinstance(display, dict) and "_approval_display_error" not in display:
                    return display
    raise ModelRetry("The approved details are unavailable. Prepare the action for review again.")
