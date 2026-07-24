# apps/api/utils/digests.py

"""Shared cryptographic digest helpers."""

import hashlib
from collections.abc import AsyncIterator


def sha256_hex(data: bytes) -> str:
    """Return a lowercase SHA-256 hex digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return a lowercase SHA-256 hex digest for UTF-8 text."""
    return sha256_hex(text.encode("utf-8"))


async def sha256_hex_stream(chunks: AsyncIterator[bytes]) -> str:
    """Return a lowercase SHA-256 digest for an async byte stream."""
    hasher = hashlib.sha256()
    async for chunk in chunks:
        hasher.update(chunk)
    return hasher.hexdigest()
