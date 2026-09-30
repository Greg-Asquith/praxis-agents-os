"""Document worker handlers that probe process limits. Loaded only by tests."""

import os
import sys
import time
from dataclasses import replace

from services.documents.handlers import HANDLERS as PRODUCTION_HANDLERS
from services.documents.packages import open_package, save_package


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
    "pid": _pid,
    "environment": _environment,
    "allocate": _allocate,
    "sleep": _sleep,
    "round_trip": _round_trip,
}
