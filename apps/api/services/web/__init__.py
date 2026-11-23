# apps/api/services/web/__init__.py

"""Public-web fetch operations."""

from services.web.fetch import fetch_url
from services.web.read_page import read_page

__all__ = ["fetch_url", "read_page"]
