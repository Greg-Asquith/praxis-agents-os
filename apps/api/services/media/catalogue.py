# apps/api/services/media/catalogue.py

"""The image and video model catalogue and which of its models this deployment can call.

The models are data in ``models.toml``, validated once per process. A route is a
provider Praxis has code for; a model is available when one of its routes is
configured, and the cheapest configured route serves it.
"""

import tomllib
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.settings import settings
from services.agents.models.domain import PROVIDER_GOOGLE, ModelConfigurationError
from services.agents.models.utils import is_provider_configured
from services.agents.models.vertex_clients import google_vertex_location

MediaTask = Literal[
    "text_to_image",
    "edit_image",
    "vector_image",
    "text_to_video",
    "image_to_video",
    "reference_to_video",
    "edit_video",
    "extend_video",
]
MediaRoute = Literal["google", "openai", "runway", "replicate"]

IMAGE_TASKS: frozenset[MediaTask] = frozenset({"text_to_image", "edit_image", "vector_image"})
# Equal prices go to the earlier route.
MEDIA_ROUTE_PREFERENCE: tuple[MediaRoute, ...] = get_args(MediaRoute)
CATALOGUE_PATH = Path(__file__).with_name("models.toml")


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MediaLimits(_Record):
    """What a model accepts and produces; an empty tuple or None means not stated."""

    aspect_ratios: tuple[str, ...] = ()
    max_input_images: int | None = Field(default=None, ge=1)
    durations_seconds: tuple[int, ...] = ()
    resolutions: tuple[str, ...] = ()
    max_input_seconds: int | None = Field(default=None, ge=1)
    max_references: int | None = Field(default=None, ge=1)
    native_audio: bool = False


class MediaModelRoute(_Record):
    """One provider that serves a model, with its own model ID and price."""

    route: MediaRoute
    model: str = Field(min_length=1)
    # Provider model IDs that differ by task, such as OpenAI's separate edit model.
    task_models: dict[MediaTask, str] = Field(default_factory=dict)
    usd_per_image: Decimal | None = Field(default=None, gt=0)
    usd_per_second: Decimal | None = Field(default=None, gt=0)

    def provider_model(self, task: MediaTask) -> str:
        """Return the provider's model ID for one task."""
        return self.task_models.get(task, self.model)

    def price(self, task: MediaTask) -> Decimal:
        """Return the per-image or per-second price for one task."""
        price = self.usd_per_image if task in IMAGE_TASKS else self.usd_per_second
        if price is None:
            raise ValueError(f"The {self.route} route has no price for {task}.")
        return price


class MediaModel(_Record):
    """One image or video model, stable across the routes that serve it."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*$")
    label: str = Field(min_length=1)
    tasks: tuple[MediaTask, ...] = Field(min_length=1)
    limits: MediaLimits = MediaLimits()
    routes: tuple[MediaModelRoute, ...] = Field(min_length=1)
    lab: str = Field(min_length=1)
    processing: Literal["eu", "global", "us"]
    # One reviewed line that agents and routing read; no semicolons, which separate models.
    strengths: str = Field(min_length=1, pattern=r"^[^;]+$")
    indemnified: bool

    @model_validator(mode="after")
    def _check_routes(self) -> "MediaModel":
        names = [route.route for route in self.routes]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.id} lists a route more than once.")
        for route in self.routes:
            for task in self.tasks:
                route.price(task)
            if unknown := set(route.task_models) - set(self.tasks):
                raise ValueError(f"{self.id} names a model for tasks it lacks: {sorted(unknown)}.")
        return self


class MediaCatalogue(_Record):
    models: tuple[MediaModel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_ids(self) -> "MediaCatalogue":
        ids = [model.id for model in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError("Media model IDs must be unique.")
        return self

    def get(self, model_id: str) -> MediaModel | None:
        """Return the model with this ID, if the catalogue has it."""
        return next((model for model in self.models if model.id == model_id), None)


@cache
def media_catalogue() -> MediaCatalogue:
    """Load and validate the catalogue once per process; a bad file fails startup."""
    with CATALOGUE_PATH.open("rb") as file:
        catalogue = MediaCatalogue.model_validate(tomllib.load(file))
    default = catalogue.get(settings.DEFAULT_IMAGE_GENERATION_MODEL)
    if default is None or "text_to_image" not in default.tasks:
        raise ValueError(
            f"DEFAULT_IMAGE_GENERATION_MODEL '{settings.DEFAULT_IMAGE_GENERATION_MODEL}' isn't an image model "
            f"in {CATALOGUE_PATH.name}."
        )
    return catalogue


def default_media_model(task: MediaTask) -> MediaModel | None:
    """Return the deployment default when it can do the task, else the first available model."""
    available = available_media_models(task)
    default_id = settings.DEFAULT_IMAGE_GENERATION_MODEL if task in IMAGE_TASKS else None
    return next((model for model in available if model.id == default_id), None) or next(
        iter(available), None
    )


def media_route_configured(route: MediaRoute, provider_model: str) -> bool:
    """Return whether this deployment can call one provider model on its route."""
    # Runway (353) and Replicate (354) have no backend yet.
    if route not in ("google", "openai") or not is_provider_configured(route):
        return False
    if route == PROVIDER_GOOGLE and settings.GOOGLE_VERTEX_AI:
        try:
            google_vertex_location(provider_model)
        except ModelConfigurationError:
            return False
    return True


def available_route(model: MediaModel, task: MediaTask) -> MediaModelRoute | None:
    """Return the cheapest configured route serving the model for one task."""
    if task not in model.tasks:
        return None
    configured = [
        route
        for route in model.routes
        if media_route_configured(route.route, route.provider_model(task))
    ]
    return min(
        configured,
        key=lambda route: (route.price(task), MEDIA_ROUTE_PREFERENCE.index(route.route)),
        default=None,
    )


def available_media_models(task: MediaTask) -> tuple[MediaModel, ...]:
    """Return the catalogue's models this deployment can call for one task, in catalogue order."""
    return tuple(
        model for model in media_catalogue().models if available_route(model, task) is not None
    )
