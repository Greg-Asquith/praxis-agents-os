"""Zip-directory rejections that run before any Office library opens a file."""

import io
import os
import struct
import zipfile

import pytest

from services.documents.precheck import PackageLimits, PackageRejectedError, precheck_package
from tests.support.office_documents import office_file, rewrite_package

LIMITS = PackageLimits(
    max_entries=50, max_uncompressed_bytes=4 * 1024 * 1024, max_compression_ratio=100
)


def _unchanged(_name: str, content: bytes) -> bytes:
    return content


def _raw_zip(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def _with_content_types(entries: list[tuple[str, bytes]]) -> bytes:
    return _raw_zip([("[Content_Types].xml", b"<Types/>"), *entries])


def _utf16_macro_content_types(name: str, content: bytes) -> bytes:
    if name != "[Content_Types].xml":
        return content
    text = content.decode().replace('encoding="UTF-8"', 'encoding="UTF-16"')
    return text.replace("spreadsheetml.sheet.main+xml", "sheet.macroEnabled.main+xml").encode(
        "utf-16"
    )


def _with_declared_size(data: bytes, name: str, size: int) -> bytes:
    """Rewrites a part's declared uncompressed size in both zip headers."""
    forged = bytearray(data)
    encoded = name.encode()
    for signature, size_offset, name_offset in ((b"PK\x03\x04", 22, 30), (b"PK\x01\x02", 24, 46)):
        header = forged.find(signature)
        while forged[header + name_offset : header + name_offset + len(encoded)] != encoded:
            header = forged.find(signature, header + 1)
        struct.pack_into("<L", forged, header + size_offset, size)
    return bytes(forged)


def test_real_office_file_passes() -> None:
    precheck_package(office_file("xlsx"), LIMITS)


@pytest.mark.parametrize(
    ("hostile", "reason"),
    [
        pytest.param(
            lambda: _with_content_types([("xl/bomb.xml", b"\0" * (2 * 1024 * 1024))]),
            "ratio",
            id="zip-bomb",
        ),
        pytest.param(
            lambda: _with_content_types(
                [(f"part{index}.bin", os.urandom(512 * 1024)) for index in range(9)]
            ),
            "expands",
            id="uncompressed-total",
        ),
        pytest.param(
            lambda: _with_content_types([(f"p{index}.xml", b"") for index in range(60)]),
            "parts",
            id="too-many-entries",
        ),
        pytest.param(
            lambda: _with_content_types([("../../etc/cron.d/x", b"")]),
            "unsafe",
            id="path-traversal",
        ),
        pytest.param(
            lambda: _with_content_types([("Word/document.xml", b""), ("word/document.xml", b"")]),
            "duplicate",
            id="duplicate-names",
        ),
        pytest.param(
            lambda: rewrite_package(
                office_file("xlsx"), _unchanged, {"xl/vbaProject.bin": b"macro"}
            ),
            "macros",
            id="macro-part",
        ),
        pytest.param(
            lambda: rewrite_package(office_file("xlsx"), _utf16_macro_content_types),
            "macros",
            id="macro-format-utf16",
        ),
        pytest.param(
            lambda: _with_declared_size(
                _with_content_types([("xl/bomb.xml", b"\0" * (2 * 1024 * 1024))]), "xl/bomb.xml", 8
            ),
            "declared",
            id="forged-size",
        ),
    ],
)
def test_hostile_archive_is_rejected(hostile, reason: str) -> None:
    with pytest.raises(PackageRejectedError, match=reason):
        precheck_package(hostile(), LIMITS)
