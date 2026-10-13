# apps/renderer/tests/test_isolation.py

"""Isolation rules for renderer children. Linux only; run with make media-renderer-check."""

import errno
import os
import signal
import struct
import sys
import time
from pathlib import Path

import pytest
from driver import isolation
from driver.child import kill_stray_processes, run_child
from driver.isolation import ChildLimits, IsolationError, build_seccomp_filter
from driver.self_check import check_isolation

LIMITS = ChildLimits(memory_bytes=512 * 1024**2, cpu_seconds=30, max_file_bytes=1024**2)


def _python(code: str) -> list[str]:
    return [sys.executable, "-E", "-s", "-c", code]


def test_child_cannot_open_an_inet_socket(tmp_path: Path) -> None:
    result = run_child(
        _python("import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)"),
        workdir=tmp_path,
        limits=LIMITS,
        timeout_seconds=20,
    )

    assert result.returncode != 0
    assert "PermissionError" in result.stderr_tail


def test_self_check_fails_closed_without_the_seccomp_filter() -> None:
    check_isolation()

    with pytest.raises(IsolationError, match="inet_socket"):
        check_isolation(seccomp=False)


@pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
def test_seccomp_filter_decides_each_rule(machine: str) -> None:
    # Evaluates the program directly; a host's own seccomp profile can't stand in for a rule.
    arch = isolation._ARCHES[machine]
    program = build_seccomp_filter(machine)
    deny = isolation.SECCOMP_RET_ERRNO | errno.EPERM
    kill = isolation.SECCOMP_RET_KILL_PROCESS
    inet, unix = 2, isolation.AF_UNIX

    for number in arch.denied_calls:
        assert _evaluate(program, arch.audit_arch, number) == deny
    for number in arch.socket_calls:
        assert _evaluate(program, arch.audit_arch, number, inet) == deny
        assert _evaluate(program, arch.audit_arch, number, unix) == isolation.SECCOMP_RET_ALLOW
    assert _evaluate(program, arch.audit_arch, 63) == isolation.SECCOMP_RET_ALLOW
    assert _evaluate(program, 0x40000003, 63) == kill
    if arch.has_x32:
        assert _evaluate(program, arch.audit_arch, isolation.X32_SYSCALL_BIT | 41, unix) == kill


def _evaluate(program: bytes, audit_arch: int, number: int, arg0: int = 0) -> int:
    # seccomp_data: nr, arch, instruction pointer, then six 64-bit arguments.
    data = struct.pack("iIQQ", number, audit_arch, 0, arg0)
    instructions = [struct.unpack("HBBI", program[i : i + 8]) for i in range(0, len(program), 8)]
    accumulator, pc = 0, 0
    while True:
        code, jt, jf, k = instructions[pc]
        if code == isolation.BPF_LD_W_ABS:
            accumulator = struct.unpack_from("I", data, k)[0]
        elif code == isolation.BPF_RET_K:
            return k
        elif code in {isolation.BPF_JEQ_K, isolation.BPF_JGE_K}:
            taken = accumulator == k if code == isolation.BPF_JEQ_K else accumulator >= k
            pc += jt if taken else jf
        pc += 1


def test_child_over_its_memory_limit_fails(tmp_path: Path) -> None:
    result = run_child(
        _python("bytearray(1024 * 1024 * 1024)"),
        workdir=tmp_path,
        limits=ChildLimits(memory_bytes=256 * 1024**2, cpu_seconds=30, max_file_bytes=1024**2),
        timeout_seconds=20,
    )

    assert result.returncode != 0
    assert "MemoryError" in result.stderr_tail


def test_child_over_its_cpu_limit_is_killed(tmp_path: Path) -> None:
    limits = ChildLimits(memory_bytes=512 * 1024**2, cpu_seconds=1, max_file_bytes=1024**2)

    result = run_child(
        _python("while True: pass"), workdir=tmp_path, limits=limits, timeout_seconds=20
    )

    assert not result.timed_out
    assert result.signal in {signal.SIGXCPU, signal.SIGKILL}


def test_child_cannot_write_past_its_file_size_limit(tmp_path: Path) -> None:
    result = run_child(
        _python("open('big', 'wb').write(bytes(2 * 1024 * 1024))"),
        workdir=tmp_path,
        limits=LIMITS,
        timeout_seconds=20,
    )

    assert result.returncode != 0
    assert (tmp_path / "big").stat().st_size <= LIMITS.max_file_bytes


def test_child_cannot_fork_past_its_process_limit(tmp_path: Path) -> None:
    limits = ChildLimits(
        memory_bytes=512 * 1024**2, cpu_seconds=30, max_file_bytes=1024**2, max_processes=1
    )

    result = run_child(
        _python("import os; os.fork()"), workdir=tmp_path, limits=limits, timeout_seconds=20
    )

    assert result.returncode != 0
    assert "BlockingIOError" in result.stderr_tail


def test_timed_out_child_is_killed_with_its_process_group(tmp_path: Path) -> None:
    code = (
        "import subprocess, time; "
        "p = subprocess.Popen(['sleep', '60']); "
        "open('grandchild.pid', 'w').write(str(p.pid)); time.sleep(60)"
    )
    started = time.monotonic()

    result = run_child(_python(code), workdir=tmp_path, limits=LIMITS, timeout_seconds=2)

    assert result.timed_out
    assert time.monotonic() - started < 10
    grandchild = int((tmp_path / "grandchild.pid").read_text())
    assert _dies(grandchild)


def test_stray_sweep_kills_a_child_that_left_its_process_group(tmp_path: Path) -> None:
    code = (
        "import subprocess; "
        "p = subprocess.Popen(['sleep', '60'], start_new_session=True); "
        "open('escaped.pid', 'w').write(str(p.pid))"
    )
    run_child(_python(code), workdir=tmp_path, limits=LIMITS, timeout_seconds=20)
    escaped = int((tmp_path / "escaped.pid").read_text())
    assert _alive(escaped)

    kill_stray_processes()

    assert _dies(escaped)


def test_stray_sweep_empties_a_detached_process_that_keeps_forking(tmp_path: Path) -> None:
    # Each generation forks a detached successor and exits, so one scan always misses one.
    code = (
        "import os\n"
        "if os.fork(): os._exit(0)\n"
        "while True:\n"
        "    os.setsid()\n"
        "    if os.fork(): os._exit(0)\n"
    )
    run_child(_python(code), workdir=tmp_path, limits=LIMITS, timeout_seconds=20)
    time.sleep(0.2)

    kill_stray_processes()

    assert _live_strays() == []


def _live_strays() -> list[int]:
    keep, pid = {os.getpid()}, os.getpid()
    while pid > 1:
        pid = int(_status(pid)["PPid"])
        keep.add(pid)
    strays = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit() and int(entry.name) not in keep:
            status = _status(int(entry.name))
            if (
                status
                and int(status["Uid"].split()[0]) == os.getuid()
                and status["State"][0] != "Z"
            ):
                strays.append(int(entry.name))
    return strays


def _status(pid: int) -> dict[str, str]:
    try:
        lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    except FileNotFoundError:
        return {}
    return dict(line.split(":\t", 1) for line in lines if ":\t" in line)


def _alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


def _dies(pid: int) -> bool:
    deadline = time.monotonic() + 5
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True
