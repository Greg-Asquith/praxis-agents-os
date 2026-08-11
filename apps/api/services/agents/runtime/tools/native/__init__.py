# apps/api/services/agents/runtime/tools/native/__init__.py

"""Provider-native runtime tool registrations."""

from services.agents.runtime.tools.native import (
    image_editing as image_editing,
    image_generation as image_generation,
    video_to_image as video_to_image,
    web_fetch as web_fetch,
    web_search as web_search,
)
from services.agents.runtime.tools.native.image_editing import (
    EditImageOutput,
    resolve_image_editing_model,
)
from services.agents.runtime.tools.native.image_generation import (
    GenerateImageOutput,
    resolve_image_generation_model,
    run_native_image_generation,
)
from services.agents.runtime.tools.native.video_to_image import (
    VideoToImageOutput,
    resolve_video_to_image_model,
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
    "EditImageOutput",
    "GenerateImageOutput",
    "VideoToImageOutput",
    "WebFetchOutput",
    "WebSearchOutput",
    "image_editing",
    "image_generation",
    "resolve_image_editing_model",
    "resolve_image_generation_model",
    "resolve_video_to_image_model",
    "resolve_web_fetch_model",
    "resolve_web_search_model",
    "run_native_image_generation",
    "run_native_web_fetch",
    "run_native_web_search",
    "video_to_image",
    "web_fetch",
    "web_search",
]
