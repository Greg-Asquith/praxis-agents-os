# apps/renderer/driver/launcher.py

"""Installs the child's limits and seccomp filter, then execs the command.

Run as ``python -E -s launcher.py <config json> -- <argv>``. The filter and
limits survive exec, so the command never runs without them.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from driver.isolation import ChildLimits, install_limits, install_seccomp_filter


def main() -> None:
    config = json.loads(sys.argv[1])
    if sys.argv[2] != "--" or len(sys.argv) < 4:
        raise SystemExit("usage: launcher.py <config json> -- <argv>")
    argv = sys.argv[3:]
    install_limits(ChildLimits(**config["limits"]))
    if config["seccomp"]:
        install_seccomp_filter()
    os.execv(argv[0], argv)  # noqa: S606


if __name__ == "__main__":
    main()
