# apps/api/services/data_science/__init__.py

"""Calls to the isolated data science service."""

from services.data_science.run_forecast import run_forecast

__all__ = ["run_forecast"]
