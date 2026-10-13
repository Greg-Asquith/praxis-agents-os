# apps/api/services/media/captions.py

"""Burned-in captions: an ASS subtitle file built from transcript words on a clip's timeline.

Words come from a provider reading untrusted audio. They reach the renderer only
inside this file, with every character that could open an override block or
break a line replaced, and wrapped by us to a bounded line length. Styling is a
preset with optional overrides; every override is a name from a fixed list, a
bounded number, or a #RRGGBB colour.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.media.domain import TranscriptWord

CaptionPreset = Literal["bold", "clean", "highlight"]
CaptionPosition = Literal["top", "middle", "lower"]
CaptionFont = Literal[
    "Anton",
    "Archivo Black",
    "Bangers",
    "Bebas Neue",
    "Inter",
    "Lato",
    "Lilita One",
    "Luckiest Guy",
    "Montserrat",
    "Noto Sans",
    "Open Sans",
    "Oswald",
    "Permanent Marker",
    "Poppins",
    "Roboto",
    "Rubik",
]
Colour = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


@dataclass(frozen=True)
class _Font:
    # Average capital glyph width in ems, measured on the bundled files.
    width: float
    has_bold: bool


# The renderer image bundles these (apps/renderer/media/fonts.lock).
FONTS: dict[str, _Font] = {
    "Anton": _Font(0.42, has_bold=False),
    "Archivo Black": _Font(0.68, has_bold=False),
    "Bangers": _Font(0.37, has_bold=False),
    "Bebas Neue": _Font(0.35, has_bold=False),
    "Inter": _Font(0.61, has_bold=True),
    "Lato": _Font(0.58, has_bold=True),
    "Lilita One": _Font(0.53, has_bold=False),
    "Luckiest Guy": _Font(0.52, has_bold=False),
    "Montserrat": _Font(0.64, has_bold=True),
    "Noto Sans": _Font(0.59, has_bold=True),
    "Open Sans": _Font(0.59, has_bold=True),
    "Oswald": _Font(0.48, has_bold=True),
    "Permanent Marker": _Font(0.61, has_bold=False),
    "Poppins": _Font(0.58, has_bold=True),
    "Roboto": _Font(0.56, has_bold=True),
    "Rubik": _Font(0.58, has_bold=True),
}
# Pixel sizes are given for a 1080 pixel short edge and scaled to the clip.
REFERENCE_EDGE_PX = 1080
# A caption breaks at a pause this long, and stays up at most this long after its last word.
CUE_PAUSE_MS = 700
CUE_HOLD_MS = 500
_SENTENCE_END = re.compile(r"[.?!][\"')\]]*$")


class CaptionOptions(BaseModel):
    """Overrides for a caption preset; anything omitted keeps the preset's value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    font: CaptionFont | None = None
    size: float | None = Field(
        default=None, ge=2, le=15, description="Font size, percent of the frame's short edge."
    )
    bold: bool | None = Field(default=None, description="Ignored for single-weight fonts.")
    uppercase: bool | None = None
    text_color: Colour | None = None
    highlight_color: Colour | None = Field(
        default=None, description="The spoken word's colour, for highlight."
    )
    highlight_scale: int | None = Field(
        default=None, ge=100, le=150, description="The spoken word's size, percent, for highlight."
    )
    outline_color: Colour | None = None
    outline_width: int | None = Field(
        default=None, ge=0, le=20, description="Pixels at 1080p; the box padding when box is on."
    )
    shadow: int | None = Field(default=None, ge=0, le=20, description="Pixels at 1080p.")
    box: bool | None = Field(
        default=None, description="A box behind the text instead of an outline."
    )
    box_color: Colour | None = None
    box_opacity: int | None = Field(default=None, ge=0, le=100, description="Percent.")
    words_per_caption: int | None = Field(default=None, ge=1, le=12)
    max_lines: int | None = Field(default=None, ge=1, le=3)
    position: CaptionPosition | None = None
    margin: float | None = Field(
        default=None,
        ge=0,
        le=40,
        description=(
            "Distance from the top or bottom edge, percent of the frame's height. Defaults keep "
            "clear of the platform's own buttons and text."
        ),
    )


_COMMON = {
    "text_color": "#FFFFFF",
    "highlight_color": "#FFD400",
    "highlight_scale": 100,
    "outline_color": "#000000",
    "shadow": 0,
    "box_color": "#000000",
    "box_opacity": 60,
    "max_lines": 2,
    "position": "lower",
}
PRESETS: dict[str, CaptionOptions] = {
    "bold": CaptionOptions(
        **_COMMON,
        font="Montserrat",
        size=7.5,
        bold=True,
        uppercase=False,
        outline_width=6,
        box=False,
        words_per_caption=4,
    ),
    "clean": CaptionOptions(
        **_COMMON,
        font="Inter",
        size=5.5,
        bold=False,
        uppercase=False,
        outline_width=14,
        box=True,
        words_per_caption=10,
    ),
    "highlight": CaptionOptions(
        **{**_COMMON, "highlight_scale": 110},
        font="Montserrat",
        size=7.5,
        bold=True,
        uppercase=True,
        outline_width=6,
        box=False,
        words_per_caption=3,
    ),
}


@dataclass(frozen=True)
class CaptionStyle:
    preset: CaptionPreset
    options: CaptionOptions = field(default_factory=CaptionOptions)


@dataclass(frozen=True)
class _Look:
    """A preset with its overrides applied, sized for one clip."""

    options: CaptionOptions
    highlight: bool
    font_size: int
    scale: float
    margins: tuple[int, int, int]
    alignment: int
    line_chars: int


def caption_file(
    words: Sequence[TranscriptWord], *, size: tuple[int, int], style: CaptionStyle
) -> str:
    """Returns an ASS file showing ``words`` (on the output timeline) in short cues."""
    look = _look(style, size)
    events = []
    cues = _cues(words, look)
    for index, cue in enumerate(cues):
        following = cues[index + 1][0].start_ms if index + 1 < len(cues) else None
        start, end = _cue_times(cue, following)
        if look.highlight:
            events += _highlight_events(cue, start, end, look)
        else:
            events.append(_dialogue(start, end, _text(cue, look)))
    return _header(size, look) + "".join(events)


def escape_caption_text(text: str) -> str:
    """Makes a transcript word inert in ASS: no override blocks, escapes, or control characters."""
    visible = "".join(
        character for character in text if unicodedata.category(character) not in {"Cc", "Cf"}
    )
    return visible.replace("\\", "\N{SET MINUS}").replace("{", "(").replace("}", ")")


def _look(style: CaptionStyle, size: tuple[int, int]) -> _Look:
    options = PRESETS[style.preset].model_copy(update=style.options.model_dump(exclude_none=True))
    width, height = size
    font = FONTS[options.font]
    font_size = round(min(width, height) * options.size / 100)
    if height > width:
        # Reels, Shorts, and TikTok put a header at the top, buttons on the right, and the
        # account and description at the foot.
        sides, default_margin = (0.08, 0.16), {"top": 12, "middle": 0, "lower": 24}
    else:
        sides, default_margin = (0.06, 0.06), {"top": 8, "middle": 0, "lower": 8}
    margin = default_margin[options.position] if options.margin is None else options.margin
    margins = (round(width * sides[0]), round(width * sides[1]), round(height * margin / 100))
    highlight = style.preset == "highlight"
    grown = options.highlight_scale / 100 if highlight else 1
    usable = width - margins[0] - margins[1]
    return _Look(
        options=options.model_copy(update={"bold": options.bold and font.has_bold}),
        highlight=highlight,
        font_size=font_size,
        scale=min(width, height) / REFERENCE_EDGE_PX,
        margins=margins,
        alignment={"top": 8, "middle": 5, "lower": 2}[options.position],
        line_chars=max(4, int(usable / (font_size * font.width * grown))),
    )


def _cues(words: Sequence[TranscriptWord], look: _Look) -> list[list[TranscriptWord]]:
    """Groups words into cues that fit the look's lines, breaking at sentences and pauses."""
    cues: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in words:
        if escape_caption_text(word.text).strip() == "":
            continue
        if current and (
            word.start_ms - current[-1].end_ms >= CUE_PAUSE_MS
            or word.speaker != current[-1].speaker
            or _SENTENCE_END.search(current[-1].text)
            or len(current) == look.options.words_per_caption
            or len(_lines([*current, word], look)) > look.options.max_lines
        ):
            cues.append(current)
            current = []
        current.append(word)
    if current:
        cues.append(current)
    return cues


def _lines(cue: Sequence[TranscriptWord], look: _Look) -> list[list[tuple[int, str]]]:
    """Wraps a cue's words into lines of (word index, piece); a long word is split."""
    limit = look.line_chars
    lines: list[list[tuple[int, str]]] = [[]]
    for index, word in enumerate(cue):
        text = escape_caption_text(word.text).strip()
        if look.options.uppercase:
            text = text.upper()
        for piece in (text[start : start + limit] for start in range(0, len(text), limit)):
            used = sum(len(item) for _, item in lines[-1]) + len(lines[-1])
            if lines[-1] and used + len(piece) > limit:
                lines.append([])
            lines[-1].append((index, piece))
    return lines


def _text(cue: Sequence[TranscriptWord], look: _Look, active: int | None = None) -> str:
    grown = look.options.highlight_scale
    spoken = f"{{\\1c{_colour(look.options.highlight_color)}&\\fscx{grown}\\fscy{grown}}}"
    return "\\N".join(
        " ".join(f"{spoken}{piece}{{\\r}}" if index == active else piece for index, piece in line)
        for line in _lines(cue, look)
    )


def _highlight_events(
    cue: Sequence[TranscriptWord], start: int, end: int, look: _Look
) -> list[str]:
    """One event per word, from its start to the next word's, with that word picked out."""
    events = []
    for index in range(len(cue)):
        word_start = start if index == 0 else max(start, cue[index].start_ms)
        word_end = end if index + 1 == len(cue) else max(word_start + 10, cue[index + 1].start_ms)
        events.append(_dialogue(word_start, min(word_end, end), _text(cue, look, index)))
    return events


def _cue_times(cue: Sequence[TranscriptWord], following: int | None) -> tuple[int, int]:
    start = cue[0].start_ms
    end = cue[-1].end_ms + CUE_HOLD_MS
    if following is not None:
        end = min(end, following)
    return start, max(end, start + 100)


def _header(size: tuple[int, int], look: _Look) -> str:
    options = look.options
    text_colour = _colour(options.text_color)
    # BorderStyle 4 (libass) draws one box behind the whole caption in the back colour,
    # padded by the outline width, which is then hidden around the text; 3 would box each
    # line, and the boxes overlap.
    back_colour = (
        _colour(options.box_color, opacity=options.box_opacity) if options.box else "&H80000000"
    )
    style = ",".join(
        str(value)
        for value in (
            "Caption", options.font, look.font_size, text_colour, text_colour,
            _colour(options.outline_color, opacity=0 if options.box else 100), back_colour, -1 if options.bold else 0, 0, 0, 0,
            100, 100, 0, 0, 4 if options.box else 1, round(options.outline_width * look.scale),
            round(options.shadow * look.scale), look.alignment, *look.margins, 1,
        )
    )  # fmt: skip
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {size[0]}\n"
        f"PlayResY: {size[1]}\n"
        # Lines are wrapped here, never by libass.
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {style}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _dialogue(start_ms: int, end_ms: int, text: str) -> str:
    return f"Dialogue: 0,{_time(start_ms)},{_time(end_ms)},Caption,,0,0,0,,{text}\n"


def _time(milliseconds: int) -> str:
    centiseconds = milliseconds // 10
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    seconds, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def _colour(hex_colour: str, *, opacity: int = 100) -> str:
    # ASS colours are &HAABBGGRR, where alpha 00 is opaque.
    alpha = round(255 * (100 - opacity) / 100)
    red, green, blue = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()
