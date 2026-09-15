"""An observable slow converter for process cancellation tests."""

import os
import time
from pathlib import Path


def slow_conversion(
    data: bytes, _content_type: str, _filename: str, _max_bytes: int, _strict_utf8: bool
) -> str:
    Path(data.decode()).write_text(str(os.getpid()))
    time.sleep(60)
    return "Unexpected completion"


class WorkerDecodedBytes(bytes):
    """Rejects decoding in the caller process or more than once in the worker."""

    def __init__(self, data: bytes):
        self.parent_pid = os.getpid()
        self.decode_calls = 0

    def decode(self, *args, **kwargs):
        assert os.getpid() != self.parent_pid
        self.decode_calls += 1
        assert self.decode_calls == 1
        return super().decode(*args, **kwargs)
