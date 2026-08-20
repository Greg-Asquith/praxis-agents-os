# apps/api/services/runtime_catalogs/assemble_runtime_catalogs.py

"""Explicitly assembles process-wide runtime catalogs."""

from threading import Lock

from services.agents.runtime.entity_references.internal import (
    register_internal_entity_resolvers,
)
from services.integrations.loader import load_enabled_providers

_catalogs_assembled = False
_catalogs_assembly_failure: Exception | None = None
_catalogs_assembly_lock = Lock()


def assemble_runtime_catalogs() -> None:
    """Assembles the job, entity resolver, and runtime tool catalogs once."""
    global _catalogs_assembled, _catalogs_assembly_failure

    with _catalogs_assembly_lock:
        if _catalogs_assembled:
            return
        if _catalogs_assembly_failure is not None:
            raise RuntimeError("Runtime catalog assembly previously failed") from (
                _catalogs_assembly_failure
            )

        try:
            _assemble_runtime_catalogs()
        except Exception as exc:
            _catalogs_assembly_failure = exc
            raise
        _catalogs_assembled = True


def _assemble_runtime_catalogs() -> None:
    """Imports and registers every process-wide runtime contribution."""
    # Registration order lets provider validation resolve platform-owned job kinds.
    from services.jobs.handlers import (
        converge_application_encryption,
        embed_kb_chunks,
        embed_memory,
        extract_file_markdown,
        ingest_kb_document,
        provision_workspace_bucket,
        rotate_credential_encryption,
        summarize_conversation_history,
        sweep_deleted_files,
        sweep_deleted_kb_documents,
        sweep_expired_agent_run_approvals,
        sweep_expired_artifact_shares,
        sweep_expired_audit_events,
        sweep_expired_memories,
        sweep_expired_scratch,
        sweep_expired_security_events,
        sweep_rate_limit_attempts,
        sweep_terminal_jobs,
    )

    _ = (
        converge_application_encryption,
        embed_kb_chunks,
        embed_memory,
        extract_file_markdown,
        ingest_kb_document,
        provision_workspace_bucket,
        rotate_credential_encryption,
        summarize_conversation_history,
        sweep_deleted_files,
        sweep_deleted_kb_documents,
        sweep_expired_agent_run_approvals,
        sweep_expired_artifact_shares,
        sweep_expired_audit_events,
        sweep_expired_memories,
        sweep_expired_scratch,
        sweep_expired_security_events,
        sweep_rate_limit_attempts,
        sweep_terminal_jobs,
    )

    from services.integrations.discovery import handlers as integration_discovery_handlers
    from services.integrations.events import handlers as integration_event_handlers

    _ = (integration_discovery_handlers, integration_event_handlers)

    register_internal_entity_resolvers()

    from services.agents.runtime.tools import (
        artifacts,
        charting,
        code_mode,
        completion,
        kb,
        memory,
        planning,
    )
    from services.agents.runtime.tools.files import list_files, read_file, write_file
    from services.agents.runtime.tools.native import (
        classifier,
        image_editing,
        image_generation,
        run_code,
        video_to_image,
        web_fetch,
        web_search,
    )

    _ = (
        artifacts,
        charting,
        classifier,
        code_mode,
        completion,
        image_editing,
        image_generation,
        kb,
        list_files,
        memory,
        planning,
        read_file,
        run_code,
        video_to_image,
        web_fetch,
        web_search,
        write_file,
    )

    load_enabled_providers()
