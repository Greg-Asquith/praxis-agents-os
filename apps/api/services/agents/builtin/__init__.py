# apps/api/services/agents/builtin/__init__.py

"""The built-in agent every workspace receives."""

from services.agents.builtin.create_builtin_agent import create_builtin_agent

__all__ = ["create_builtin_agent"]
