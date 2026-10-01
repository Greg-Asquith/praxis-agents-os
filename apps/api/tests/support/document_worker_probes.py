"""Document worker handlers that probe process limits and full loads. Loaded only by tests."""

import os
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from itertools import islice
from typing import Any

from services.documents.handlers import HANDLERS as PRODUCTION_HANDLERS
from services.documents.packages import open_package, save_package

_DESCRIBE_TEXT_CHARS = 2_000


def _describe(document_format, _args, data, limits):
    """Opens a file with a full load and returns its part count and a short text sample."""
    document = open_package(data, document_format, limits)
    count, texts = _DESCRIBERS[document_format](document)
    text = "\n".join(islice(texts, 200))[:_DESCRIBE_TEXT_CHARS]
    return {"format": document_format, "count": count, "text": text}, None


def _describe_presentation(presentation: Any) -> tuple[int, Iterator[str]]:
    texts = (
        shape.text_frame.text
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    return len(presentation.slides), texts


def _describe_workbook(workbook: Any) -> tuple[int, Iterator[str]]:
    texts = (
        str(value)
        for row in workbook.worksheets[0].iter_rows(max_row=50, values_only=True)
        for value in row
        if value is not None
    )
    return len(workbook.worksheets), texts


def _describe_document(document: Any) -> tuple[int, Iterator[str]]:
    return len(document.paragraphs), (paragraph.text for paragraph in document.paragraphs)


_DESCRIBERS = {
    "pptx": _describe_presentation,
    "xlsx": _describe_workbook,
    "docx": _describe_document,
}


def _pid(*_args):
    return {"pid": os.getpid()}, None


def _environment(*_args):
    return {"keys": sorted(os.environ), "settings_loaded": "core.settings" in sys.modules}, None


def _allocate(_format, args, *_rest):
    bytearray(args["bytes"])
    return {}, None


def _sleep(*_args):
    time.sleep(60)
    return {}, None


def _round_trip(document_format, args, data, limits):
    output_limits = replace(limits, **args.get("output_limits", {}))
    return {}, save_package(open_package(data, document_format, limits), output_limits)


HANDLERS = {
    **PRODUCTION_HANDLERS,
    "describe": _describe,
    "pid": _pid,
    "environment": _environment,
    "allocate": _allocate,
    "sleep": _sleep,
    "round_trip": _round_trip,
}
