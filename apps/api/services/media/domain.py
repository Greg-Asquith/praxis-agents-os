# apps/api/services/media/domain.py

"""Typed media renderer operations and results.

Operation fields are numbers only. Nothing a model writes reaches an ffmpeg
argument, path, or URL; the renderer builds every command line itself.
"""

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.files.domain import VideoMetadata
from services.storage.domain import StorageObjectRef

MEDIA_STAGING_PREFIX = "platform/media-staging"
INVALID_RESPONSE_MESSAGE = "The media renderer gave an invalid answer."
# Mirrors the renderer's own limits in apps/renderer/media/operations.py.
MAX_SCENE_CUTS = 2000
MIN_SCENE_THRESHOLD = 0.05
MAX_SCENE_THRESHOLD = 0.95
MAX_FRAMES = 20
MIN_FRAME_EDGE_PX = 64
MAX_FRAME_EDGE_PX = 1920
DEFAULT_FRAME_EDGE_PX = 1280
MAX_AUDIO_CHUNKS = 32
MAX_CUT_SEGMENTS = 10
MAX_CUT_SHOT_CUTS = 500
MIN_OUTPUT_EDGE_PX = 64
MAX_OUTPUT_EDGE_PX = 3840
MIN_OUTPUT_FPS = 24
MAX_OUTPUT_FPS = 60


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    # (content type, extension) of each output; empty when the operation writes none.
    output_type: ClassVar[tuple[str, str]] = ("", "")

    def renderer_arguments(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"name"}, exclude_none=True)

    def output_count(self) -> int:
        return 1 if self.output_type[0] else 0

    def input_count(self) -> int:
        return 1


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
    threshold: float = Field(default=0.3, ge=MIN_SCENE_THRESHOLD, le=MAX_SCENE_THRESHOLD)
    max_cuts: int = Field(default=MAX_SCENE_CUTS, ge=1, le=MAX_SCENE_CUTS)


class CutSegment(_Range):
    """A range of one input, by its position in the operation's sources."""

    input: int = Field(ge=0, lt=MAX_CUT_SEGMENTS)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class CutOperation(_Operation):
    """Joins segments of one or more sources into one H.264 and AAC MP4 of a fixed size.

    ``fit`` shows each whole frame over a blurred fill. ``reframe`` crops to follow the
    largest face in each shot, jumping only at ``shot_cuts_ms`` (input, time) pairs.
    Otherwise frames are centre-cropped.
    """

    name: Literal["cut"] = "cut"
    output_type: ClassVar[tuple[str, str]] = ("video/mp4", ".mp4")
    segments: tuple[CutSegment, ...] = Field(min_length=1, max_length=MAX_CUT_SEGMENTS)
    width: int = Field(ge=MIN_OUTPUT_EDGE_PX, le=MAX_OUTPUT_EDGE_PX, multiple_of=2)
    height: int = Field(ge=MIN_OUTPUT_EDGE_PX, le=MAX_OUTPUT_EDGE_PX, multiple_of=2)
    fps: int = Field(default=30, ge=MIN_OUTPUT_FPS, le=MAX_OUTPUT_FPS)
    fit: bool = False
    reframe: bool = False
    shot_cuts_ms: tuple[tuple[int, int], ...] = Field(default=(), max_length=MAX_CUT_SHOT_CUTS)

    @model_validator(mode="after")
    def require_every_input(self):
        if {segment.input for segment in self.segments} != set(range(self.input_count())):
            raise ValueError("segments must use every source from 0")
        if self.fit and self.reframe:
            raise ValueError("fit and reframe can't both be set")
        if self.shot_cuts_ms and not self.reframe:
            raise ValueError("shot_cuts_ms need reframe")
        if any(
            not 0 <= source < self.input_count() or time_ms < 0
            for source, time_ms in self.shot_cuts_ms
        ):
            raise ValueError("shot_cuts_ms must name a source and a time")
        return self

    def input_count(self) -> int:
        return len({segment.input for segment in self.segments})

    def renderer_arguments(self) -> dict[str, object]:
        return {
            "segments": [
                [segment.input, segment.start_ms, segment.end_ms] for segment in self.segments
            ],
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "fit": self.fit,
            "reframe": self.reframe,
            "shot_cuts": [list(cut) for cut in self.shot_cuts_ms],
        }


class ExtractAudioOperation(_Range):
    """Mono 16 kHz Ogg Opus speech audio, split at silences into ``chunks`` files."""

    name: Literal["extract_audio"] = "extract_audio"
    output_type: ClassVar[tuple[str, str]] = ("audio/ogg", ".ogg")
    chunks: int = Field(default=1, ge=1, le=MAX_AUDIO_CHUNKS)

    def output_count(self) -> int:
        return self.chunks


class FramesOperation(_Operation):
    name: Literal["frames"] = "frames"
    output_type: ClassVar[tuple[str, str]] = ("image/jpeg", ".jpg")
    times_ms: tuple[Annotated[int, Field(ge=0)], ...] = Field(min_length=1, max_length=MAX_FRAMES)
    max_edge_px: int = Field(
        default=DEFAULT_FRAME_EDGE_PX, ge=MIN_FRAME_EDGE_PX, le=MAX_FRAME_EDGE_PX
    )

    def output_count(self) -> int:
        return len(self.times_ms)


MediaOperation = Annotated[
    ProbeOperation | SceneCutsOperation | CutOperation | ExtractAudioOperation | FramesOperation,
    Field(discriminator="name"),
]


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SceneCutsResult(_Result):
    cuts_ms: tuple[int, ...] = Field(max_length=MAX_SCENE_CUTS)
    duration_ms: int = Field(ge=0)


class ExtractAudioResult(_Result):
    duration_ms: int = Field(ge=0)
    # Each chunk's [start_ms, end_ms] on the source video's timeline.
    chunks_ms: tuple[tuple[int, int], ...] = Field(min_length=1, max_length=MAX_AUDIO_CHUNKS)


class FramesResult(_Result):
    times_ms: tuple[int, ...]


RESULT_MODELS: dict[str, type[BaseModel]] = {
    "probe": VideoMetadata,
    "scene_cuts": SceneCutsResult,
    "cut": VideoMetadata,
    "extract_audio": ExtractAudioResult,
    "frames": FramesResult,
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

    result: VideoMetadata | SceneCutsResult | ExtractAudioResult | FramesResult
    outputs: tuple[StagedMediaOutput, ...]
    elapsed_ms: int


class TranscriptionError(Exception):
    """A transcription failure with a message safe to show an agent."""


class VideoUnderstandingError(Exception):
    """An understanding model failure with a message safe to show an agent."""


class MediaRendererError(Exception):
    """A renderer failure with a stable code and a message safe to show an agent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Transcripts: words come from a provider reading untrusted audio, so text is bounded.
MAX_TRANSCRIPT_WORD_CHARS = 100
MAX_SPEAKER_LABEL_CHARS = 16


class TranscriptWord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=MAX_TRANSCRIPT_WORD_CHARS)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    speaker: str | None = Field(default=None, max_length=MAX_SPEAKER_LABEL_CHARS)


class TranscriptSentence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    speaker: str | None = Field(default=None, max_length=MAX_SPEAKER_LABEL_CHARS)


class Transcript(BaseModel):
    """A video revision's words and sentences on the source timeline, in milliseconds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    language: str | None = None
    duration_ms: int = Field(ge=0)
    words: tuple[TranscriptWord, ...]
    sentences: tuple[TranscriptSentence, ...]
