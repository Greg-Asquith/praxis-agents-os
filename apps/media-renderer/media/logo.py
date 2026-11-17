# apps/media-renderer/media/logo.py

"""A logo for cut: one image input, scaled once with its transparency kept, at a position."""

from typing import Any

from driver.server import OperationError

LOGO_OPTIONS = ("logo_position", "logo_size", "logo_margins", "logo_opacity")
LOGO_POSITIONS = frozenset(
    {
        "top_left", "top_center", "top_right", "middle_center",
        "bottom_left", "bottom_center", "bottom_right",
    }
)  # fmt: skip
MIN_LOGO_SIZE_PX = 8
MIN_LOGO_OPACITY = 10
MAX_LOGO_OPACITY = 100


def validate_logo(arguments: dict[str, Any]) -> None:
    """Logo options come all together with logo, and none without it.

    The logo fits in a square of ``logo_size`` pixels, ``logo_margins`` (x, y) in from the edges
    its position names, and both must stay inside the frame. A centred axis ignores its margin.
    """
    given = {name for name in LOGO_OPTIONS if name in arguments}
    if given != (set(LOGO_OPTIONS) if arguments.get("logo") else set()):
        raise OperationError("invalid_request", "A logo needs all its options, and only with logo.")
    if not given:
        return
    if arguments["logo_position"] not in LOGO_POSITIONS:
        raise OperationError("invalid_request", "logo_position must name a position.")
    if not MIN_LOGO_OPACITY <= arguments["logo_opacity"] <= MAX_LOGO_OPACITY:
        raise OperationError(
            "invalid_request",
            f"logo_opacity must be {MIN_LOGO_OPACITY} to {MAX_LOGO_OPACITY}.",
        )
    size, margins = arguments["logo_size"], arguments["logo_margins"]
    if (
        len(margins) != 2
        or size < MIN_LOGO_SIZE_PX
        or min(margins) < 0
        or margins[0] + size > arguments["width"]
        or margins[1] + size > arguments["height"]
    ):
        raise OperationError("invalid_request", "The logo must fit inside the frame.")


def place_logo(filters: list[str], arguments: dict[str, Any], stream: int, video: str) -> str:
    """Places ffmpeg input `stream`, an image, over `video` for the whole clip.

    Returns the placed video's label.
    """
    size, opacity = arguments["logo_size"], arguments["logo_opacity"]
    vertical, horizontal = arguments["logo_position"].split("_")
    x, y = arguments["logo_margins"]
    left = {"left": str(x), "center": "(main_w-overlay_w)/2", "right": f"main_w-overlay_w-{x}"}
    top = {"top": str(y), "middle": "(main_h-overlay_h)/2", "bottom": f"main_h-overlay_h-{y}"}
    faded = f",colorchannelmixer=aa={opacity / 100:g}" if opacity < MAX_LOGO_OPACITY else ""
    # A single image ends after one frame; overlay then repeats it to the end of the clip.
    filters.append(
        f"[{stream}:v:0]scale=w={size}:h={size}:force_original_aspect_ratio=decrease:"
        f"flags=lanczos,format=rgba{faded}[logo]"
    )
    filters.append(f"{video}[logo]overlay=x={left[horizontal]}:y={top[vertical]}[branded]")
    return "[branded]"
