# apps/api/services/runtime_catalogs/__init__.py

"""Explicit process-wide runtime catalog composition."""

from services.runtime_catalogs.assemble_runtime_catalogs import assemble_runtime_catalogs

__all__ = ["assemble_runtime_catalogs"]
