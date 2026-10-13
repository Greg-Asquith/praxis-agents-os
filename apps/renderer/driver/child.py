# apps/renderer/driver/child.py

"""Runs one native command as an isolated child of the driver."""

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from driver.isolation import ChildLimits, IsolationError

LAUNCHER = Path(__file__).resolve().parent / "launcher.py"
STDERR_TAIL_BYTES = 16 * 1024
SURVIVOR_WAIT_SECONDS = 2


@dataclass(frozen=True)
class ChildResult:
    returncode: int
    timed_out: bool
    stdout_path: Path
    stderr_tail: str

    @property
    def signal(self) -> int | None:
        return -self.returncode if self.returncode < 0 else None


def _child_environment(workdir: Path) -> dict[str, str]:
    """Returns the only environment a child sees."""
    return {
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "PATH": "/opt/ffmpeg/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
    }


def run_child(
    argv: list[str],
    *,
    workdir: Path,
    limits: ChildLimits,
    timeout_seconds: float,
    seccomp: bool = True,
) -> ChildResult:
    """Runs argv under the limits and kills its process group when it ends or times out."""
    logs = workdir / ".logs"
    logs.mkdir(exist_ok=True)
    stdout_path = logs / f"{time.monotonic_ns()}.out"
    stderr_path = stdout_path.with_suffix(".err")
    config = json.dumps({"limits": limits.__dict__, "seccomp": seccomp})
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        # argv is built by the driver from validated fields, never from request text.
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-E", "-s", "-B", str(LAUNCHER), config, "--", *argv],
            cwd=workdir,
            env=_child_environment(workdir),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            _kill_group(process.pid)
            process.wait()
    return ChildResult(
        returncode=process.returncode,
        timed_out=timed_out,
        stdout_path=stdout_path,
        stderr_tail=_tail(stderr_path),
    )


def kill_stray_processes() -> None:
    """Kills every other process under the driver's user, then proves none is left.

    A child can leave its process group with setsid, and one that keeps forking
    outruns any /proc scan. kill(-1) signals atomically against fork and never
    signals PID 1 or the driver; require_no_shared_ancestor keeps every other
    ancestor out of reach. Raises IsolationError if anything survives, so the
    instance can be retired.
    """
    with contextlib.suppress(ProcessLookupError):
        os.kill(-1, signal.SIGKILL)
    uid, keep = os.getuid(), _ancestors(os.getpid())
    deadline = time.monotonic() + SURVIVOR_WAIT_SECONDS
    while True:
        _reap_orphans()
        if not _live_processes(uid, keep):
            return
        if time.monotonic() > deadline:
            raise IsolationError("Stray processes survived cleanup")
        time.sleep(0.01)


def require_no_shared_ancestor() -> None:
    """Refuses to run unless kill(-1) can't reach one of the driver's ancestors."""
    uid = os.getuid()
    for pid in _ancestors(os.getpid()) - {os.getpid(), 0, 1}:
        with contextlib.suppress(FileNotFoundError):
            if int(_status_field(Path(f"/proc/{pid}/status").read_text(), "Uid:")) == uid:
                raise IsolationError("The driver must be its user's first process")


def _live_processes(uid: int, keep: set[int]) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in keep:
            continue
        try:
            status = (entry / "status").read_text()
        except FileNotFoundError:
            continue
        if int(_status_field(status, "Uid:")) == uid and _status_field(status, "State:") != "Z":
            found.append(int(entry.name))
    return found


def _reap_orphans() -> None:
    # The driver is PID 1 on Cloud Run, so orphans become its children.
    with contextlib.suppress(ChildProcessError):
        while os.waitpid(-1, os.WNOHANG)[0]:
            pass


def _status_field(status: str, name: str) -> str:
    # /proc/<pid> of a non-dumpable process belongs to root, so read the status instead.
    return next(line.split()[1] for line in status.splitlines() if line.startswith(name))


def _ancestors(pid: int) -> set[int]:
    chain = {pid}
    while pid > 1:
        try:
            status = Path(f"/proc/{pid}/status").read_text()
        except FileNotFoundError:
            break
        pid = int(_status_field(status, "PPid:"))
        chain.add(pid)
    return chain


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def _tail(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - STDERR_TAIL_BYTES))
        return handle.read().decode("utf-8", "replace")
