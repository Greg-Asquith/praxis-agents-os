# apps/api/services/documents/worker_process.py

"""Entry point for one document worker process.

The pool starts this module with a minimal environment. It must not import
application settings, database, or storage modules. Requests and responses are
length-prefixed frames of a JSON header and raw bytes, so the parent never
unpickles data from a process that parsed an untrusted file.
"""

import importlib
import json
import math
import os
import resource
import struct
import sys
from typing import Any, BinaryIO

from services.documents.precheck import PackageLimits, PackageRejectedError

FRAME_PREFIX = struct.Struct(">IQ")
_MEMORY_EXIT_CODE = 70


def read_frame(stream: BinaryIO) -> tuple[dict[str, Any], bytes] | None:
    """Reads one frame, or returns None at end of input."""
    prefix = stream.read(FRAME_PREFIX.size)
    if len(prefix) < FRAME_PREFIX.size:
        return None
    header_size, payload_size = FRAME_PREFIX.unpack(prefix)
    header = json.loads(stream.read(header_size))
    return header, stream.read(payload_size)


def write_frame(stream: BinaryIO, header: dict[str, Any], payload: bytes = b"") -> None:
    encoded = json.dumps(header).encode()
    stream.write(FRAME_PREFIX.pack(len(encoded), len(payload)) + encoded + payload)
    stream.flush()


def apply_limits(memory_bytes: int, cpu_seconds: int) -> None:
    """Sets address-space and CPU limits before any Office library loads."""
    _set_cpu_budget(cpu_seconds)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ValueError, OSError):
        # macOS doesn't support RLIMIT_AS; the pool's timeout still applies locally.
        if sys.platform != "darwin":
            raise


def _set_cpu_budget(cpu_seconds: int) -> None:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    used = math.ceil(usage.ru_utime + usage.ru_stime)
    _, hard = resource.getrlimit(resource.RLIMIT_CPU)
    resource.setrlimit(resource.RLIMIT_CPU, (used + cpu_seconds, hard))


def main() -> None:
    config = json.loads(sys.argv[1])
    apply_limits(config["memory_bytes"], config["cpu_seconds"])
    handlers = importlib.import_module(config["handlers"]).HANDLERS
    from services.documents.packages import require_safe_parsers

    require_safe_parsers()
    limits = PackageLimits(**config["limits"])
    requests, responses = sys.stdin.buffer, sys.stdout.buffer
    # Keep stray library output off the protocol stream.
    sys.stdout = sys.stderr
    while (request := read_frame(requests)) is not None:
        _set_cpu_budget(config["cpu_seconds"])
        write_frame(responses, *_handle(handlers, limits, *request))


def _handle(
    handlers: dict[str, Any], limits: PackageLimits, header: dict[str, Any], payload: bytes
) -> tuple[dict[str, Any], bytes]:
    handler = handlers.get(header["operation"])
    if handler is None:
        return {"ok": False, "error": "invalid"}, b""
    try:
        result, data = handler(header["format"], header["args"], payload, limits)
    except PackageRejectedError as exc:
        return {"ok": False, "error": "rejected", "message": str(exc)}, b""
    except MemoryError:
        # Heap state is unreliable after a failed allocation, so the worker exits.
        os._exit(_MEMORY_EXIT_CODE)
    except Exception:
        return {"ok": False, "error": "unreadable"}, b""
    return {"ok": True, "result": result}, data or b""


if __name__ == "__main__":
    main()
