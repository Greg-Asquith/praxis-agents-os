<!-- apps/api/tests/fixtures/forecast_evals/README.md -->

# Forecast eval fixtures

The `forecast_*` cases in `evals/datasets/agent_behavior.yaml` use these:

- `daily_orders.csv`: 168 days of synthetic daily orders from 2026-05-18,
  with a weekly pattern, a slow rise, and dips on the UK bank holidays. The
  `ExpectedForecast` evaluator compares any literal history with this file.
- `read_table_daily_orders.json`: the `read_table` result for that CSV,
  built with the document worker's `read_table` and `file_result`, so the
  dates are untrusted nodes as in production.
- `forecast_series_daily_orders.json`: the model-visible `forecast_series`
  result for a 56-day horizon with UK holidays, built by the tool's
  `_forecast_result` from a synthetic service result.
- `forecast_series_low_reliability.json`: the same result for 52 weeks of
  small, synthetic counts that a plain average forecasts as well as the model.

Rebuild them when the `read_table` or forecast result changes, so the
evals show models what production returns.
