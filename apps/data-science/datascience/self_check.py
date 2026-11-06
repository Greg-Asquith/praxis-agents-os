# apps/data-science/datascience/self_check.py

"""Start-up check: one tiny forecast in an isolated child, through the real operation.

It proves PyTorch runs under the seccomp filter and limits, and that the weights load
offline, before the service accepts a request.
"""

import math
import shutil
import tempfile
import time
from pathlib import Path

from driver.server import DriverConfig, OperationContext

from datascience.forecast import run_forecast, validate_forecast

TIMEOUT_SECONDS = 120


def check_forecast(config: DriverConfig) -> None:
    """Raises unless a weekly pattern forecasts to finite numbers."""
    arguments = validate_forecast(
        {
            "start": "2026-01-05",
            "frequency": "daily",
            "values": [10 + 5 * math.sin(2 * math.pi * day / 7) for day in range(56)],
            "horizon": 7,
            "holiday_regions": ["uk"],
            "covariates": [],
        }
    )
    workdir = Path(tempfile.mkdtemp(prefix="ready-check-"))
    try:
        run_forecast(
            OperationContext(
                config=config,
                workdir=workdir,
                inputs=[],
                output_count=0,
                deadline=time.monotonic() + TIMEOUT_SECONDS,
            ),
            arguments,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
