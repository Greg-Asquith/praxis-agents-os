# apps/media-renderer/media/cards.py

"""Title and end cards for cut: a solid colour, with an optional image over it, in silence."""

from typing import Any

from driver.server import OperationError

from media.ffmpeg import OUTPUT_AUDIO_RATE, samples_per_frame

# A card's segment is [CARD_INPUT, 0, duration_ms]; it reads no video.
CARD_INPUT = -1
MIN_CARD_MS = 500
MAX_CARD_MS = 15000
MAX_CARD_COLOR = 0xFFFFFF


def card_positions(arguments: dict[str, Any]) -> list[int]:
    return [
        position
        for position, (index, _, _) in enumerate(arguments["segments"])
        if index == CARD_INPUT
    ]


def card_image_count(arguments: dict[str, Any]) -> int:
    return sum(image for _, image in arguments.get("cards", []))


def validate_cards(arguments: dict[str, Any]) -> None:
    """``cards`` lists one [colour, image] per card segment, in order; image is 1 when the card
    shows the next card image input over its colour.

    A card plays as it is: no speed, freeze, zoom, or removed frames.
    """
    positions = card_positions(arguments)
    cards = arguments.get("cards", [])
    if len(cards) != len(positions) or any(
        len(card) != 2 or not 0 <= card[0] <= MAX_CARD_COLOR or card[1] not in {0, 1}
        for card in cards
    ):
        raise OperationError(
            "invalid_request", "cards must list one [colour, image] per card segment."
        )
    count = len(arguments["segments"])
    speeds = arguments.get("speed_percents", [100] * count)
    freezes = arguments.get("freeze_end_ms", [0] * count)
    zooms = arguments.get("zooms", [[100, 100]] * count)
    kept = {position for position, _, _ in arguments.get("keep", [])}
    for position in positions:
        _, start, end = arguments["segments"][position]
        if start != 0 or not MIN_CARD_MS <= end <= MAX_CARD_MS:
            raise OperationError(
                "invalid_request", f"A card lasts {MIN_CARD_MS} to {MAX_CARD_MS} ms."
            )
        if (
            speeds[position] != 100
            or freezes[position]
            or zooms[position] != [100, 100]
            or position in kept
        ):
            raise OperationError(
                "invalid_request", "A card has no speed, freeze, zoom, or removed frames."
            )


def card_filters(
    position: int,
    color: int,
    image_stream: int | None,
    size: tuple[int, int],
    frames: int,
    fps: int,
) -> list[str]:
    """Builds [vN] and [aN] for a card, exactly ``frames`` long.

    An image covers the frame, cropped to its shape, over the colour, so its transparent parts
    show the colour.
    """
    width, height = size
    background = f"color=c=0x{color:06X}:s={width}x{height}:r={fps},setsar=1"
    filters = []
    if image_stream is None:
        picture = background
    else:
        filters.append(f"{background}[back{position}]")
        filters.append(
            f"[{image_stream}:v:0]scale={width}:{height}:force_original_aspect_ratio=increase:"
            f"flags=lanczos,crop={width}:{height},setsar=1,format=rgba[front{position}]"
        )
        # A single image ends after one frame; overlay then repeats it over the colour.
        picture = f"[back{position}][front{position}]overlay"
    return [
        *filters,
        f"{picture},format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[v{position}]",
        f"anullsrc=r={OUTPUT_AUDIO_RATE}:cl=stereo,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=end_sample={frames * samples_per_frame(fps)},asetpts=PTS-STARTPTS[a{position}]",
    ]
