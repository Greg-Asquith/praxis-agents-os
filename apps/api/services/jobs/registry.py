# apps/api/services/jobs/registry.py

"""Job handler registry."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import iscoroutinefunction
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from services.jobs.domain import is_valid_job_kind

if TYPE_CHECKING:
    from models.jobs import Job


JobHandler = Callable[[AsyncSession, "Job"], Awaitable[None]]


@dataclass(frozen=True)
class JobHandlerDefinition:
    kind: str
    function: JobHandler
    timeout: float | None = None
    max_attempts: int | None = None


JOB_HANDLERS: dict[str, JobHandlerDefinition] = {}


def job_handler(
    *,
    kind: str,
    timeout: float | None = None,
    max_attempts: int | None = None,
) -> Callable[[JobHandler], JobHandler]:
    """Register an async handler for a job kind."""
    if not is_valid_job_kind(kind):
        raise RuntimeError(f"Invalid job kind: {kind}")
    if kind in JOB_HANDLERS:
        raise RuntimeError(f"Duplicate job handler kind: {kind}")
    if timeout is not None and timeout <= 0:
        raise RuntimeError("Job handler timeout must be greater than zero")
    if max_attempts is not None and max_attempts <= 0:
        raise RuntimeError("Job handler max_attempts must be greater than zero")

    def decorator(function: JobHandler) -> JobHandler:
        if not iscoroutinefunction(function):
            raise RuntimeError(f"Job handler for kind '{kind}' must be async")
        JOB_HANDLERS[kind] = JobHandlerDefinition(
            kind=kind,
            function=function,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        return function

    return decorator


def get_job_handler(kind: str) -> JobHandlerDefinition | None:
    """Return the registered handler definition for a kind, if any."""
    return JOB_HANDLERS.get(kind)


# Assembly point for built-in handlers and future plan-owned handlers.
from services.jobs import handlers as _handlers  # noqa: E402,F401
