"""UTF-8 byte windows shared by workspace and integration file reads."""

from dataclasses import dataclass


class TextWindowError(ValueError):
    """The requested window cannot preserve UTF-8 character boundaries."""


@dataclass(frozen=True)
class TextWindow:
    content: str
    offset: int
    end_offset: int
    total_bytes: int


def utf8_window(data: bytes, *, offset: int, max_bytes: int) -> TextWindow:
    """Returns one character-aligned window of valid UTF-8 bytes."""
    total = len(data)
    if offset < 0:
        raise TextWindowError("offset must be non-negative.")
    if offset > total:
        raise TextWindowError(f"offset is beyond the content length ({total} bytes).")
    if not _is_utf8_boundary(data, offset):
        raise TextWindowError("offset must be a UTF-8 character boundary; use a prior end_offset.")
    if max_bytes < 1:
        raise TextWindowError("max_bytes must be greater than 0.")
    end = _previous_utf8_boundary(data, min(offset + max_bytes, total), lower_bound=offset)
    if end == offset and offset < total:
        width = _next_utf8_char_width(data[offset])
        raise TextWindowError(
            f"max_bytes is too small to include the next UTF-8 character; use at least {width}."
        )
    return TextWindow(data[offset:end].decode("utf-8"), offset, end, total)


def _is_utf8_boundary(data: bytes, index: int) -> bool:
    return index == 0 or index == len(data) or (data[index] & 0b1100_0000) != 0b1000_0000


def _previous_utf8_boundary(data: bytes, index: int, *, lower_bound: int) -> int:
    while index > lower_bound and not _is_utf8_boundary(data, index):
        index -= 1
    return index


def _next_utf8_char_width(first_byte: int) -> int:
    if first_byte < 0b1000_0000:
        return 1
    if first_byte & 0b1110_0000 == 0b1100_0000:
        return 2
    if first_byte & 0b1111_0000 == 0b1110_0000:
        return 3
    if first_byte & 0b1111_1000 == 0b1111_0000:
        return 4
    return 1
