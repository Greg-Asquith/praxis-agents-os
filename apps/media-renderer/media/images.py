# apps/media-renderer/media/images.py

"""Still images as inputs: one PNG, JPEG, or WebP file, checked before anything decodes it."""

from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import FFPROBE, read_json

# Each pipe demuxer finds its format from the file's content and reads that one file, never
# a name pattern; the decoder must match it.
IMAGE_CODECS = {"png_pipe": "png", "jpeg_pipe": "mjpeg", "webp_pipe": "webp"}
MAX_IMAGE_EDGE_PX = 4096
MAX_IMAGE_BYTES = 20_971_520  # 20 MB
# Decoders refuse a frame larger than the biggest allowed image before allocating it.
MAX_IMAGE_PIXELS = MAX_IMAGE_EDGE_PX * MAX_IMAGE_EDGE_PX


def image_input(context: OperationContext, index: int) -> list[str]:
    """Input options that read one image, after checking its format, file size, and size."""
    path = context.fetch_input(index)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise OperationError(
            "invalid_media", f"The image is larger than {MAX_IMAGE_BYTES // 1024**2} MB."
        )
    try:
        report = read_json(
            context.run(
                [
                    FFPROBE, "-v", "error", "-max_pixels", str(MAX_IMAGE_PIXELS),
                    "-print_format", "json", "-show_format", "-show_streams", path.name,
                ]
            )
        )  # fmt: skip
    except OperationError as exc:
        if exc.code != "invalid_media":
            raise
        raise OperationError("invalid_media", "The image couldn't be read.") from exc
    demuxer, stream = _image_stream(report)
    width, height = stream.get("width") or 0, stream.get("height") or 0
    if not (0 < width <= MAX_IMAGE_EDGE_PX and 0 < height <= MAX_IMAGE_EDGE_PX):
        raise OperationError(
            "invalid_media",
            f"The image must be at most {MAX_IMAGE_EDGE_PX} pixels on each side.",
        )
    return ["-f", demuxer, "-max_pixels", str(MAX_IMAGE_PIXELS), "-i", path.name]


def _image_stream(report: Any) -> tuple[str, dict[str, Any]]:
    """Returns the demuxer and only stream of a PNG, JPEG, or WebP file."""
    demuxer = (report.get("format") or {}).get("format_name")
    streams = report.get("streams") or []
    if (
        demuxer not in IMAGE_CODECS
        or len(streams) != 1
        or streams[0].get("codec_name") != IMAGE_CODECS[demuxer]
    ):
        raise OperationError("invalid_media", "The image isn't a PNG, JPEG, or WebP file.")
    return demuxer, streams[0]
