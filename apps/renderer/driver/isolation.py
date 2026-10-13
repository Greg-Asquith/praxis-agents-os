# apps/renderer/driver/isolation.py

"""Child process isolation: resource limits, no_new_privs, and a seccomp filter.

The filter kills foreign architectures and x32
calls, allows only AF_UNIX sockets, and refuses io_uring, ptrace, and
cross-process memory access with EPERM. Linux only.
"""

import ctypes
import errno
import platform
import resource
import struct
from dataclasses import dataclass

PR_SET_NO_NEW_PRIVS = 38
PR_SET_DUMPABLE = 4
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2

SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000

BPF_LD_W_ABS = 0x20
BPF_JEQ_K = 0x15
BPF_JGE_K = 0x35
BPF_RET_K = 0x06

SECCOMP_DATA_NR = 0
SECCOMP_DATA_ARCH = 4
SECCOMP_DATA_ARG0 = 16

AF_UNIX = 1
X32_SYSCALL_BIT = 0x40000000


@dataclass(frozen=True)
class _Arch:
    audit_arch: int
    socket_calls: tuple[int, ...]
    denied_calls: tuple[int, ...]
    has_x32: bool


# Denied: io_uring_setup, io_uring_enter, io_uring_register, ptrace,
# process_vm_readv, process_vm_writev.
_ARCHES = {
    "x86_64": _Arch(0xC000003E, (41, 53), (425, 426, 427, 101, 310, 311), True),
    "aarch64": _Arch(0xC00000B7, (198, 199), (425, 426, 427, 117, 270, 271), False),
}


@dataclass(frozen=True)
class ChildLimits:
    """Per-child resource limits, installed before exec."""

    memory_bytes: int
    cpu_seconds: int
    max_file_bytes: int
    max_processes: int = 512


class IsolationError(RuntimeError):
    """Raised when a limit or the seccomp filter can't be installed."""


def _instruction(code: int, jt: int, jf: int, k: int) -> bytes:
    return struct.pack("HBBI", code, jt, jf, k)


def build_seccomp_filter(machine: str | None = None) -> bytes:
    """Builds the BPF program for this machine's architecture."""
    arch = _ARCHES.get(machine or platform.machine())
    if arch is None:
        raise IsolationError(f"No seccomp filter for architecture {machine or platform.machine()}")

    deny = SECCOMP_RET_ERRNO | errno.EPERM
    program: list[tuple[int, int, int, int]] = [
        (BPF_LD_W_ABS, 0, 0, SECCOMP_DATA_ARCH),
        (BPF_JEQ_K, 1, 0, arch.audit_arch),
        (BPF_RET_K, 0, 0, SECCOMP_RET_KILL_PROCESS),
        (BPF_LD_W_ABS, 0, 0, SECCOMP_DATA_NR),
    ]
    if arch.has_x32:
        program += [
            (BPF_JGE_K, 0, 1, X32_SYSCALL_BIT),
            (BPF_RET_K, 0, 0, SECCOMP_RET_KILL_PROCESS),
        ]
    # Each socket call jumps over the remaining checks to the domain check.
    checks = len(arch.socket_calls) + len(arch.denied_calls)
    for index, number in enumerate(arch.socket_calls):
        program.append((BPF_JEQ_K, checks - index + 1, 0, number))
    for index, number in enumerate(arch.denied_calls):
        remaining = len(arch.denied_calls) - index - 1
        program.append((BPF_JEQ_K, remaining + 1, 0, number))
    program += [
        (BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW),
        (BPF_RET_K, 0, 0, deny),
        (BPF_LD_W_ABS, 0, 0, SECCOMP_DATA_ARG0),
        (BPF_JEQ_K, 0, 1, AF_UNIX),
        (BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW),
        (BPF_RET_K, 0, 0, deny),
    ]
    return b"".join(_instruction(*item) for item in program)


def _prctl(option: int, *args: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(option, *(ctypes.c_ulong(arg) for arg in args)) != 0:
        code = ctypes.get_errno()
        raise IsolationError(f"prctl({option}) failed: {errno.errorcode.get(code, code)}")


def install_seccomp_filter() -> None:
    """Sets no_new_privs and installs the filter on the calling process."""
    program = build_seccomp_filter()
    count = len(program) // 8
    buffer = ctypes.create_string_buffer(program, len(program))

    class SockFprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    fprog = SockFprog(count, ctypes.cast(buffer, ctypes.c_void_p))
    _prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
    _prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(fprog), 0, 0)


def install_limits(limits: ChildLimits) -> None:
    """Applies the child's resource limits to the calling process."""
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_file_bytes, limits.max_file_bytes))
    resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def make_driver_undumpable() -> None:
    """Stops children reading the driver's memory or /proc environment."""
    _prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
