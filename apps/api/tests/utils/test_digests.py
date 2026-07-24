# apps/api/tests/utils/test_digests.py

"""Shared digest helper coverage."""

import hashlib

from utils.digests import sha256_hex, sha256_hex_stream, sha256_text


def test_sha256_helpers_cover_bytes_and_utf8_text() -> None:
    text = "Praxis 漢字"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()

    assert sha256_hex(text.encode("utf-8")) == expected
    assert sha256_text(text) == expected


async def test_sha256_hex_stream_preserves_chunk_order() -> None:
    async def chunks():
        for chunk in (b"Pra", b"xis"):
            yield chunk

    assert await sha256_hex_stream(chunks()) == hashlib.sha256(b"Praxis").hexdigest()
