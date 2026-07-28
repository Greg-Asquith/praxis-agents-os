# apps/api/services/jobs/handlers/__init__.py

"""Built-in generic job handlers."""

from services.jobs.handlers import (
    embed_kb_chunks,  # noqa: F401
    embed_memory,  # noqa: F401
    extract_file_markdown,  # noqa: F401
    ingest_kb_document,  # noqa: F401
    integration_discovery,  # noqa: F401
    integration_events,  # noqa: F401
    rotate_credential_encryption,  # noqa: F401
    summarize_conversation_history,  # noqa: F401
    sweep_deleted_files,  # noqa: F401
    sweep_deleted_kb_documents,  # noqa: F401
    sweep_expired_artifact_shares,  # noqa: F401
    sweep_expired_memories,  # noqa: F401
    sweep_expired_scratch,  # noqa: F401
    sweep_rate_limit_attempts,  # noqa: F401
    sweep_terminal_jobs,  # noqa: F401
)
