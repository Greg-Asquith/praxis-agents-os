// apps/web/tests/support/forecast.ts

// A forecast_series public result: six days of history and a one-day horizon.
export function forecastPublicResult(overrides: { baseline?: boolean } = {}) {
  const withBaseline = overrides.baseline ?? true
  const band = (median: number[]) => ({
    median,
    low: median.map((value) => value - 10),
    high: median.map((value) => value + 10),
  })
  return {
    title: "Daily Orders",
    unit: "orders",
    frequency: "daily",
    method: "Timestral 123M",
    history_points: 6,
    forecast: [],
    backtest: {
      periods: 2,
      starting_points: 3,
      tested_points: 6,
      typical_error: 0.05,
      range_coverage: 1,
      simple_method: "average",
      simple_error: 0.2,
      covariate_error_change: withBaseline ? -0.31 : null,
    },
    holidays: [{ date: "2026-12-25", region: "uk", name: "Christmas Day", share: 1 }],
    covariates_used: withBaseline,
    reliability: "limited",
    caveats: ["The test covered only 6 periods, so its accuracy figures are rough."],
    chart: {
      periods: [
        "2026-12-20",
        "2026-12-21",
        "2026-12-22",
        "2026-12-23",
        "2026-12-24",
        "2026-12-25",
        "2026-12-26",
      ],
      history: [100, 110, null, 120, 100, 200],
      forecast: band([150]),
      baseline: withBaseline ? band([160]) : null,
      backtest: {
        forecast: { typical_error: 0.05, range_coverage: 1 },
        baseline: withBaseline ? { typical_error: 0.12, range_coverage: 0.5 } : null,
      },
      covariates: [
        {
          name: "UK Holidays",
          source: "holiday",
          timing: "known_future",
          kind: "number",
          values: [0, 0, 0, 0, 0, 1, 0],
          labels: null,
        },
      ],
    },
  }
}
