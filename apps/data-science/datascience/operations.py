# apps/data-science/datascience/operations.py

"""The operations the data science service offers. None takes signed inputs or outputs."""

from driver.server import Operation

from datascience.forecast import run_forecast, validate_forecast

OPERATIONS: dict[str, Operation] = {
    "forecast": Operation(
        validate=validate_forecast,
        output_count=lambda arguments: 0,
        run=run_forecast,
        input_count=lambda arguments: 0,
    ),
}
