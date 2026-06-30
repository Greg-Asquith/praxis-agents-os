# apps/api/services/agents/runtime/__init__.py

"""Pydantic AI runtime core for executing one agent turn."""

from typing import Any

# execute_run is intentionally not re-exported here: the submodule services.agents.runtime.execute_run shadows any same-named package attribute, so import the function explicitly via that module path.
__all__ = [
    "run_task_registry",
    "sweep_abandoned_agent_runs_on_startup",
]


def __getattr__(name: str) -> Any:
    if name == "run_task_registry":
        from services.agents.runtime.run_manager import run_task_registry

        return run_task_registry
    if name == "sweep_abandoned_agent_runs_on_startup":
        from services.agents.runtime.lifespan import sweep_abandoned_agent_runs_on_startup

        return sweep_abandoned_agent_runs_on_startup
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
