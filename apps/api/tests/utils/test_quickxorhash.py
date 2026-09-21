"""QuickXorHash vectors and an independent bit-level reference."""

import base64

import pytest

from utils.quickxorhash import quickxorhash


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", "AAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        (b"A", "QQAAAAAAAAAAAAAAAQAAAAAAAAA="),
        (b"The quick brown fox jumps over the lazy dog", "bMSlbysmxJL6S75XwfMcQZOpcr4="),
    ],
)
def test_fixed_vectors(data, expected):
    assert quickxorhash(data) == expected


@pytest.mark.parametrize("size", [20, 160, 161, 255, 1025])
def test_wraparound_and_length_match_bit_reference(size):
    data = bytes(index % 256 for index in range(size))
    result = bytearray(20)
    for index, byte in enumerate(data):
        for bit in range(8):
            position = (index * 11 + bit) % 160
            result[position // 8] ^= ((byte >> bit) & 1) << (position % 8)
    for index, byte in enumerate(len(data).to_bytes(8, "little")):
        result[index + 12] ^= byte
    assert quickxorhash(data) == base64.b64encode(result).decode("ascii")
