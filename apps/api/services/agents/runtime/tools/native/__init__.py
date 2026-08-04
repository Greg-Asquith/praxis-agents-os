# apps/api/services/agents/runtime/tools/native/__init__.py

"""Provider-native runtime tool registrations."""

from services.agents.runtime.tools.native import web_fetch as web_fetch, web_search as web_search
from services.agents.runtime.tools.native.web_fetch import (
    WebFetchOutput,
    resolve_web_fetch_model,
    run_native_web_fetch,
)
from services.agents.runtime.tools.native.web_search import (
    WebSearchOutput,
    resolve_web_search_model,
    run_native_web_search,
)

__all__ = [
    "WebFetchOutput",
    "WebSearchOutput",
    "resolve_web_fetch_model",
    "resolve_web_search_model",
    "run_native_web_fetch",
    "run_native_web_search",
    "web_fetch",
    "web_search",
]
