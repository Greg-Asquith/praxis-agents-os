"""Shared UTF-8 byte boundary behaviour."""

import pytest

from utils.text_window import TextWindowError, utf8_window


@pytest.mark.parametrize(
    "text,offset,max_bytes,content,end",
    [
        ("a界😀z", 0, 4, "a界", 4),
        ("a界😀z", 0, 3, "a", 1),
        ("a界😀z", 4, 4, "😀", 8),
        ("a界😀z", 9, 4, "", 9),
        ("", 0, 4, "", 0),
    ],
)
def test_window_preserves_boundaries(text, offset, max_bytes, content, end):
    window = utf8_window(text.encode(), offset=offset, max_bytes=max_bytes)
    assert (window.content, window.offset, window.end_offset, window.total_bytes) == (
        content,
        offset,
        end,
        len(text.encode()),
    )


@pytest.mark.parametrize(
    "offset,max_bytes,message",
    [
        (10, 4, "content length (9 bytes)"),
        (2, 4, "character boundary"),
        (4, 3, "use at least 4"),
        (-1, 4, "non-negative"),
        (0, 0, "greater than 0"),
    ],
)
def test_invalid_windows_fail(offset, max_bytes, message):
    with pytest.raises(TextWindowError) as caught:
        utf8_window("a界😀z".encode(), offset=offset, max_bytes=max_bytes)
    assert message in str(caught.value)
