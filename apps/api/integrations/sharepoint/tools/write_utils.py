# apps/api/integrations/sharepoint/tools/write_utils.py

"""Resolves write targets and records bounded SharePoint mutation evidence."""

from pydantic import ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.general import AppValidationError
from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.audit_events import (
    AuditStatus,
    IntegrationOperationCounts,
    IntegrationOperationEffect,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationOutcome,
    IntegrationOperationOutcomeGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
)
from services.files.contract import is_editable
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.utils import integration_failure_code
from services.integrations.write_lifecycle import (
    IntegrationWriteCallbacks,
    PreparedIntegrationWrite,
)

from ..operations.file_source import load_file_source, resolve_file_source
from ..operations.get_item import get_item
from ..operations.utils import file_error, item_kind
from ..operations.write_utils import DriveWriteState
from ..settings import sharepoint_settings
from .utils import SHAREPOINT_DRIVE_WRITE_BINDING, bounded_output, drive_client

PreparedDriveWrite = PreparedIntegrationWrite


def write_entry(deps, reference=None):
    active = deps.active_context
    entries = active.compatible_entries(SHAREPOINT_DRIVE_WRITE_BINDING) if active else ()
    if reference is not None:
        matching = [entry for entry in entries if entry.external_id == reference.drive_id]
    else:
        matching = [entry for entry in entries if entry.write_allowed]
        if not matching and len(entries) == 1:
            matching = list(entries)
    if len(matching) != 1:
        raise ModelRetry(
            "Select one writable SharePoint library, or choose a folder in a selected library."
        )
    entry = matching[0]
    if sum(other.external_id == entry.external_id for other in entries) != 1:
        raise ModelRetry("Select the SharePoint library only once before saving a file.")
    return entry


async def mutation_display_args(input_model, deps, args: dict) -> dict:
    values = validate_input(input_model, args)
    reference = (
        getattr(values, "file", None)
        or getattr(values, "folder", None)
        or getattr(values, "parent", None)
    )
    entry = write_entry(deps, reference)
    if getattr(values, "content", None) is not None:
        content_bytes(values.content)
    display = values.model_dump(mode="json") | {
        "_library": entry.display_name[:500],
        "_target": target_identity(entry),
    }

    if getattr(values, "source", None) is not None:
        source = await resolve_file_source(
            deps.db, workspace=deps.workspace, reference=values.source
        )
        display["_source"] = source.approval_details()
    return display


def target_identity(entry) -> dict[str, str]:
    return {
        "drive_id": entry.external_id,
        "resource_id": str(entry.integration_resource_id),
        "connection_id": str(entry.connection_id),
    }


def verify_approved_target(ctx, entry, reference) -> None:
    reviewed = approved_display_args(ctx).get("_target")
    current = target_identity(entry)
    if not isinstance(reviewed, dict) or reviewed.keys() != current.keys():
        raise ModelRetry(
            "The approved library is unavailable. Prepare the action for review again."
        )
    if not all(isinstance(value, str) and value for value in reviewed.values()):
        raise ModelRetry(
            "The approved library is unavailable. Prepare the action for review again."
        )
    # Resume validates explicit destination edits; an omitted root cannot authorise a new library.
    if reference is not None and reference.drive_id != reviewed["drive_id"]:
        return
    if reviewed != current:
        raise ModelRetry(
            "The selected library changed after review. Prepare the action for approval again."
        )


def validate_input(input_model, args: dict):
    try:
        return input_model.model_validate(args)
    except (ValidationError, IntegrationError):
        raise ModelRetry("Review the SharePoint name, text, and required fields.") from None


def content_bytes(content: str) -> bytes:
    data = content.encode("utf-8")
    if len(data) > sharepoint_settings.SHAREPOINT_FILE_MAX_UPLOAD_BYTES:
        raise ModelRetry("This file exceeds the upload limit. Save a smaller file.")
    return data


def require_editable_content_type(value: object, *, operation: str) -> None:
    try:
        if isinstance(value, str) and is_editable(value):
            return
    except AppValidationError:
        pass
    raise file_error(
        "Select a text file to replace with text.", "unsupported_type", operation=operation
    )


async def require_parent(client, *, drive_id, reference, operation):
    if reference is None:
        return None
    item = await get_item(client, drive_id=drive_id, item_id=reference.item_id)
    if item_kind(item, operation=operation) != "folder":
        raise file_error(
            "Choose a folder as the destination.", "unsupported_type", operation=operation
        )
    return reference.item_id


def pending_write_detail(
    entry, *, action, size_bytes=0, content_type=None, expected_version=None, item_id=None
):
    return PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="sharepoint_drive",
            external_id=entry.external_id,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"file:{action}",
                action=action,
                entity_type="sharepoint_drive_item",
                external_id=item_id,
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "action": action,
                            "size_bytes": size_bytes,
                            "content_type": content_type,
                            "expected_version": expected_version,
                        }
                    )
                ],
            )
        ],
    )


def write_result(state, *, outcome, error_code=None, detail=None):
    return {"item": state.item, "outcome": outcome, "error_code": error_code, "detail": detail}


def terminal_detail(entry, pending, state, *, status, error_code=None):
    external_ref = f"{entry.external_id}:{state.item_id}" if state.item_id else None
    fields = {
        "etag_before": state.etag_before,
        "etag_after": state.etag_after,
        "size_bytes": pending.intent_groups[0].items[0].fields["size_bytes"],
        "hash_matched": state.hash_matched,
        "session_created": state.session_created,
        "session_status": state.session_status,
        "bytes_sent": state.bytes_sent,
        "committed": state.committed,
        "item_ref": external_ref,
    }
    effect = IntegrationOperationEffect(
        status=status,
        fields=fields,
        error_code=error_code,
        external_ref=external_ref if status == "applied" else None,
    )
    counts = IntegrationOperationCounts(
        applied=int(status == "applied"),
        skipped=0,
        failed=int(status == "failed"),
        unverified=int(status == "unverified"),
    )
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=[
            IntegrationOperationOutcomeGroup(
                key=pending.intent_groups[0].key,
                outcomes=[
                    IntegrationOperationOutcome(intent_index=0, status=status, effects=[effect])
                ],
            )
        ],
        intent_counts=counts,
        effect_counts=counts,
    )


def write_outcome(entry, pending, state, *, status, error_code=None, detail=None):
    result = write_result(state, outcome=status, error_code=error_code, detail=detail)
    return IntegrationAuditOutcome(
        result,
        status={
            "applied": AuditStatus.SUCCESS,
            "failed": AuditStatus.FAILURE,
            "unverified": AuditStatus.UNVERIFIED,
        }[status],
        external_ref=f"{entry.external_id}:{state.item_id}" if state.item_id else None,
        operation_detail=terminal_detail(
            entry, pending, state, status=status, error_code=error_code
        ),
        unverified_result=result if status == "unverified" else None,
    )


def failed_write_outcome(entry, pending, state, exc):
    ambiguous = getattr(exc, "failure_disposition", None) in {
        None,
        IntegrationFailureDisposition.AMBIGUOUS,
    }
    return write_outcome(
        entry,
        pending,
        state,
        status="unverified" if ambiguous else "failed",
        error_code="unverified_mutation" if ambiguous else integration_failure_code(exc),
        detail=(
            "SharePoint could not confirm the saved file. Check it before trying again."
            if ambiguous
            else exc.user_message
            if isinstance(exc, IntegrationError)
            else "The file could not be saved."
        ),
    )


def attach_write_cancellation(entry, exc, pending, state):
    disposition = getattr(exc, "failure_disposition", IntegrationFailureDisposition.AMBIGUOUS)
    exc.failure_disposition = disposition
    exc.operation_detail = terminal_detail(
        entry,
        pending,
        state,
        status="unverified" if disposition == IntegrationFailureDisposition.AMBIGUOUS else "failed",
        error_code="cancelled",
    )


class DriveWriteCallbacks(IntegrationWriteCallbacks):
    def __init__(self, entry, state, prepare_operation):
        super().__init__(
            prepare_operation=prepare_operation,
            successful=lambda pending: write_outcome(entry, pending, state, status="applied"),
            failed=lambda pending, exc: failed_write_outcome(entry, pending, state, exc),
            cancelled=lambda exc, pending: attach_write_cancellation(entry, exc, pending, state),
        )


async def run_drive_write(ctx, *, entry, action, prepare, reference=None, source=None):
    async def operation(entry):
        state = DriveWriteState()

        async def prepare_operation():
            verify_approved_target(ctx, entry, reference)
            source_file = None
            if source is not None:
                source_file = await load_file_source(
                    ctx.deps.db,
                    workspace=ctx.deps.workspace,
                    reference=source,
                    pinned=approved_display_args(ctx).get("_source"),
                )
            client = await drive_client(ctx, entry)
            return await prepare(client, state, source_file)

        callbacks = DriveWriteCallbacks(entry, state, prepare_operation)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name=f"sharepoint_{action}",
            operation=action,
            execute=callbacks.execute,
            prepare_pending_operation=callbacks.prepare,
        )

    return bounded_output(
        await run_context_scope(
            ctx,
            binding=SHAREPOINT_DRIVE_WRITE_BINDING,
            provider_scope_id=entry.external_id,
            operation=operation,
        )
    )
