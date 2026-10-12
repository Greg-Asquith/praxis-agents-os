# apps/renderer/driver/isolation_probe.py

"""Self-check probe, run as an isolated child. Prints which escapes succeeded."""

import ctypes
import json
import os
import platform
import signal
import socket
import sys

PTRACE_ATTACH = 16
NR_IO_URING_SETUP = 425
NR_PTRACE = {"x86_64": 101, "aarch64": 117}
IO_URING_PARAMS_BYTES = 120


def _succeeds(action) -> bool:
    try:
        return bool(action())
    except OSError:
        return False


def _inet_socket(family: int) -> bool:
    socket.socket(family, socket.SOCK_STREAM).close()
    return True


def _unix_socket() -> bool:
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close()
    return True


def _syscall(*args) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    return libc.syscall(*args)


def _io_uring_setup() -> bool:
    # Valid arguments, so only a denial can make the call fail.
    params = ctypes.create_string_buffer(IO_URING_PARAMS_BYTES)
    descriptor = _syscall(ctypes.c_long(NR_IO_URING_SETUP), ctypes.c_long(1), params)
    if descriptor < 0:
        return False
    os.close(descriptor)
    return True


def _ptrace_own_child() -> bool:
    # The probe's own child is a target the kernel would otherwise let it trace.
    child = os.fork()
    if child == 0:
        signal.pause()
        os._exit(0)
    try:
        return (
            _syscall(
                *(
                    ctypes.c_long(arg)
                    for arg in (NR_PTRACE[platform.machine()], PTRACE_ATTACH, child, 0, 0)
                )
            )
            >= 0
        )
    finally:
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)


def _read_driver_environ(driver_pid: int) -> bool:
    with open(f"/proc/{driver_pid}/environ", "rb") as handle:
        return bool(handle.read(1))


def main() -> None:
    driver_pid = int(sys.argv[1])
    escapes = {
        "inet_socket": _succeeds(lambda: _inet_socket(socket.AF_INET)),
        "inet6_socket": _succeeds(lambda: _inet_socket(socket.AF_INET6)),
        "io_uring_setup": _succeeds(_io_uring_setup),
        "ptrace": _succeeds(_ptrace_own_child),
        "driver_environ": _succeeds(lambda: _read_driver_environ(driver_pid)),
    }
    report = {"escapes": escapes, "unix_socket": _succeeds(_unix_socket)}
    print(json.dumps(report))  # noqa: T201


if __name__ == "__main__":
    main()
