# apps/api/services/documents/precheck.py

"""Archive checks that run in the document worker before any Office library opens a file.

Imported by the document worker process, so it uses the standard library and
defusedxml only.
"""

import io
import struct
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

OFFICE_FORMATS = frozenset({"pptx", "xlsx", "docx"})
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_ENCRYPTED_FLAG = 0x1
_CONTENT_TYPES_PART = "[content_types].xml"
_MACRO_PART = "vbaproject.bin"
_MAX_CONTENT_TYPES_BYTES = 1024 * 1024
# Small parts such as blank XML compress far past any sane ratio; total size bounds them.
_RATIO_CHECK_MIN_BYTES = 1024 * 1024
_LOCAL_HEADER = struct.Struct("<4s2B4HL2L2H")
_LOCAL_HEADER_SIGNATURE = b"PK\x03\x04"
_INFLATE_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class PackageLimits:
    max_entries: int
    max_uncompressed_bytes: int
    max_compression_ratio: int


class PackageRejectedError(Exception):
    """An Office file failed a structural check and was not opened."""


def precheck_package(data: bytes, limits: PackageLimits) -> None:
    """Rejects archives that are unsafe to hand to an Office library."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, EOFError):
        raise PackageRejectedError("The file isn't a valid Office document.") from None
    with archive:
        entries = archive.infolist()
    if len(entries) > limits.max_entries:
        raise PackageRejectedError(f"The file has more than {limits.max_entries} parts.")
    _check_entries(entries, limits)
    content_types = None
    for entry in entries:
        content = _inflate(data, entry, limits)
        if entry.filename.lower() == _CONTENT_TYPES_PART:
            content_types = content
    if content_types is None:
        raise PackageRejectedError("The file isn't a valid Office document.")
    _check_content_types(content_types)


def _check_entries(entries: list[zipfile.ZipInfo], limits: PackageLimits) -> None:
    seen: set[str] = set()
    total = 0
    for entry in entries:
        name = _checked_name(entry.filename)
        if name in seen:
            raise PackageRejectedError("The file has duplicate part names.")
        seen.add(name)
        if PurePosixPath(name).name == _MACRO_PART:
            raise PackageRejectedError("The file contains macros, which aren't supported.")
        if entry.flag_bits & _ENCRYPTED_FLAG:
            raise PackageRejectedError("The file is encrypted or password protected.")
        if entry.compress_type not in _ALLOWED_COMPRESSION:
            raise PackageRejectedError("The file uses an unsupported compression method.")
        total += entry.file_size
        if total > limits.max_uncompressed_bytes:
            raise PackageRejectedError("The file expands beyond the allowed size.")


def _checked_name(filename: str) -> str:
    path = PurePosixPath(filename)
    if (
        not path.parts
        or "\\" in filename
        or path.is_absolute()
        or ".." in path.parts
        or ":" in path.parts[0]
    ):
        raise PackageRejectedError("The file contains an unsafe part name.")
    # Office part names are case-insensitive.
    return filename.lower()


def _inflate(data: bytes, entry: zipfile.ZipInfo, limits: PackageLimits) -> bytes | None:
    """Decompresses one part within its declared size and checks the actual result.

    `zipfile.read()` inflates everything and then trims to the declared size,
    so declared sizes alone don't bound memory. Only [Content_Types].xml is kept.
    """
    compressed = _compressed_bytes(data, entry)
    keep = entry.filename.lower() == _CONTENT_TYPES_PART
    if keep and entry.file_size > _MAX_CONTENT_TYPES_BYTES:
        raise PackageRejectedError("The file isn't a valid Office document.")
    inflater = (
        None if entry.compress_type == zipfile.ZIP_STORED else zlib.decompressobj(-zlib.MAX_WBITS)
    )
    kept: list[bytes] = []
    size = crc = 0
    for chunk in _chunks(compressed, inflater, entry.file_size + 1):
        size += len(chunk)
        crc = zlib.crc32(chunk, crc)
        if keep:
            kept.append(bytes(chunk))
    if size != entry.file_size or crc != entry.CRC:
        raise PackageRejectedError("The file's parts don't match their declared sizes.")
    consumed = len(compressed)
    if inflater is not None:
        consumed -= len(inflater.unused_data) + len(inflater.unconsumed_tail)
    if size >= _RATIO_CHECK_MIN_BYTES and size > max(consumed, 1) * limits.max_compression_ratio:
        raise PackageRejectedError("The file is compressed beyond the allowed ratio.")
    return b"".join(kept) if keep else None


def _chunks(compressed: memoryview, inflater: Any, max_bytes: int) -> Iterator[bytes | memoryview]:
    """Yields at most max_bytes of part content, a bounded chunk at a time."""
    if inflater is None:
        for start in range(0, min(len(compressed), max_bytes), _INFLATE_CHUNK_BYTES):
            yield compressed[start : min(start + _INFLATE_CHUNK_BYTES, max_bytes)]
        return
    produced = 0
    pending: bytes | memoryview = compressed
    try:
        while pending and produced < max_bytes and not inflater.eof:
            chunk = inflater.decompress(pending, min(_INFLATE_CHUNK_BYTES, max_bytes - produced))
            pending = inflater.unconsumed_tail
            produced += len(chunk)
            yield chunk
    except zlib.error:
        raise PackageRejectedError("The file isn't a valid Office document.") from None


def _compressed_bytes(data: bytes, entry: zipfile.ZipInfo) -> memoryview:
    offset = entry.header_offset
    if offset < 0 or offset + _LOCAL_HEADER.size > len(data):
        raise PackageRejectedError("The file isn't a valid Office document.")
    fields = _LOCAL_HEADER.unpack_from(data, offset)
    if fields[0] != _LOCAL_HEADER_SIGNATURE:
        raise PackageRejectedError("The file isn't a valid Office document.")
    start = offset + _LOCAL_HEADER.size + fields[10] + fields[11]
    end = start + entry.compress_size
    if end > len(data):
        raise PackageRejectedError("The file isn't a valid Office document.")
    return memoryview(data)[start:end]


def _check_content_types(content: bytes) -> None:
    from xml.etree.ElementTree import ParseError

    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import fromstring

    try:
        root = fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException):
        raise PackageRejectedError("The file isn't a valid Office document.") from None
    for element in root.iter():
        if "macroenabled" in element.get("ContentType", "").lower():
            raise PackageRejectedError("The file contains macros, which aren't supported.")
