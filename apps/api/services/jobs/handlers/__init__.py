# apps/api/services/jobs/handlers/__init__.py

"""Built-in generic job handlers."""

from services.jobs.handlers import (
    extract_file_markdown,  # noqa: F401
    sweep_deleted_files,  # noqa: F401
    sweep_terminal_jobs,  # noqa: F401
)
