# apps/api/services/agents/runtime/tools/native/__init__.py

"""Provider-native runtime tool registrations."""

from services.agents.runtime.tools.native import (
    image_generation as image_generation,
    web_fetch as web_fetch,
    web_search as web_search,
)
from services.agents.runtime.tools.native.image_generation import (
    GenerateImageOutput,
    resolve_image_generation_model,
    run_native_image_generation,
)
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
    "GenerateImageOutput",
    "WebFetchOutput",
    "WebSearchOutput",
    "image_generation",
    "resolve_image_generation_model",
    "resolve_web_fetch_model",
    "resolve_web_search_model",
    "run_native_image_generation",
    "run_native_web_fetch",
    "run_native_web_search",
    "web_fetch",
    "web_search",
]
