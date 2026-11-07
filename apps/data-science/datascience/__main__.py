# apps/data-science/datascience/__main__.py

"""Starts the data science service."""

from driver.server import serve

from datascience.operations import OPERATIONS
from datascience.self_check import check_forecast

# Series travel inline, so requests are larger than the media renderer's 64 KiB.
# 32,768 points with eight known-future covariates is about 6 MB of JSON.
MAX_REQUEST_BYTES = 8 * 1024 * 1024

serve(OPERATIONS, max_request_bytes=MAX_REQUEST_BYTES, transfers=False, ready_check=check_forecast)
