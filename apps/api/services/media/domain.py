# apps/api/services/media/domain.py

"""Typed media renderer operations and results.

Operation fields are numbers only. Nothing a model writes reaches an ffmpeg
argument, path, or URL; the renderer builds every command line itself.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.files.domain import VideoMetadata
from services.storage.domain import StorageObjectRef

MEDIA_STAGING_PREFIX = "platform/media-staging"


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    def renderer_arguments(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"name"}, exclude_none=True)


class _Range(_Operation):
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_order(self):
        if self.end_ms is not None and self.end_ms <= (self.start_ms or 0):
            raise ValueError("end_ms must be after start_ms")
        return self


class ProbeOperation(_Operation):
    name: Literal["probe"] = "probe"


class SceneCutsOperation(_Range):
    name: Literal["scene_cuts"] = "scene_cuts"
    threshold: float = Field(default=0.3, ge=0.05, le=0.95)
    max_cuts: int = Field(default=2000, ge=1, le=2000)


class CutOperation(_Range):
    name: Literal["cut"] = "cut"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class ExtractAudioOperation(_Range):
    name: Literal["extract_audio"] = "extract_audio"


class FramesOperation(_Operation):
    name: Literal["frames"] = "frames"
    times_ms: tuple[Annotated[int, Field(ge=0)], ...] = Field(min_length=1, max_length=20)
    max_edge_px: int = Field(default=1280, ge=64, le=1920)


MediaOperation = Annotated[
    ProbeOperation | SceneCutsOperation | CutOperation | ExtractAudioOperation | FramesOperation,
    Field(discriminator="name"),
]


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SceneCutsResult(_Result):
    cuts_ms: tuple[int, ...] = Field(max_length=2000)
    duration_ms: int = Field(ge=0)


class CutResult(VideoMetadata):
    mode: Literal["copy", "encode"]


class ExtractAudioResult(_Result):
    duration_ms: int = Field(ge=0)


class FramesResult(_Result):
    times_ms: tuple[int, ...]


RESULT_MODELS: dict[str, type[BaseModel]] = {
    "probe": VideoMetadata,
    "scene_cuts": SceneCutsResult,
    "cut": CutResult,
    "extract_audio": ExtractAudioResult,
    "frames": FramesResult,
}

# (content type, extension) of each output an operation writes.
OUTPUT_TYPES: dict[str, tuple[str, str]] = {
    "cut": ("video/mp4", ".mp4"),
    "extract_audio": ("audio/mp4", ".m4a"),
    "frames": ("image/jpeg", ".jpg"),
}


class StagedMediaOutput(BaseModel):
    """A renderer output in platform staging, not yet a File."""

    model_config = ConfigDict(frozen=True)

    ref: StorageObjectRef
    content_type: str
    extension: str
    size_bytes: int
    sha256: str


class MediaOperationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: VideoMetadata | SceneCutsResult | CutResult | ExtractAudioResult | FramesResult
    outputs: tuple[StagedMediaOutput, ...]
    elapsed_ms: int


class MediaRendererError(Exception):
    """A renderer failure with a stable code and a message safe to show an agent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
