# apps/renderer/driver/self_check.py

"""Fail-closed isolation self-check, run before the driver accepts a request."""

import json
import os
import sys
import tempfile
from pathlib import Path

from driver.child import require_no_shared_ancestor, run_child
from driver.isolation import ChildLimits, IsolationError

PROBE = Path(__file__).resolve().parent / "isolation_probe.py"
PROBE_LIMITS = ChildLimits(
    memory_bytes=512 * 1024 * 1024,
    cpu_seconds=10,
    max_file_bytes=1024 * 1024,
)


def check_isolation(*, seccomp: bool = True) -> None:
    """Raises IsolationError unless an isolated child can't escape its limits."""
    require_no_shared_ancestor()
    with tempfile.TemporaryDirectory(prefix="self-check-") as directory:
        result = run_child(
            [sys.executable, "-E", "-s", "-B", str(PROBE), str(os.getpid())],
            workdir=Path(directory),
            limits=PROBE_LIMITS,
            timeout_seconds=20,
            seccomp=seccomp,
        )
        if result.returncode != 0:
            raise IsolationError(f"Isolation probe failed: {result.stderr_tail.strip()[-500:]}")
        report = json.loads(result.stdout_path.read_text())
    escaped = sorted(name for name, succeeded in report["escapes"].items() if succeeded)
    if escaped:
        raise IsolationError(f"Isolated child could {', '.join(escaped)}")
    if not report["unix_socket"]:
        raise IsolationError("Isolation probe couldn't run normally")
