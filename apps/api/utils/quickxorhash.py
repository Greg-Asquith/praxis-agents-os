# apps/api/utils/quickxorhash.py

"""Computes Microsoft's 160-bit QuickXorHash for file verification."""

from base64 import b64encode
from functools import reduce
from operator import xor


def quickxorhash(data: bytes) -> str:
    """Returns the base64 hash used by SharePoint and OneDrive file metadata."""
    value = 0
    mask = (1 << 160) - 1
    # A byte's rotation repeats every 160 positions, so fold each column first.
    for index in range(min(len(data), 160)):
        column = reduce(xor, data[index::160], 0)
        shifted = column << ((index * 11) % 160)
        value ^= (shifted & mask) | (shifted >> 160)
    value ^= len(data) << 96
    return b64encode(value.to_bytes(20, "little")).decode("ascii")
