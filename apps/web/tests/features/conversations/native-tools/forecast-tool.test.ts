// apps/web/tests/features/conversations/native-tools/forecast-tool.test.ts

import { describe, expect, it } from "vitest"

import {
  forecastBacktestSummary,
  forecastToolResult,
} from "@/features/conversations/native-tools/forecast-tool"
import { forecastPublicResult } from "../../../support/forecast"

describe("forecastBacktestSummary", () => {
  it("scores the forecast without covariates against the held-out history", () => {
    const result = forecastToolResult(forecastPublicResult())
    if (!result) throw new Error("expected a forecast result")

    // Actuals 100 and 200 against 95 (85 to 105) and 230 (220 to 240).
    const summary = forecastBacktestSummary(result, false)

    expect(summary.typicalError).toBeCloseTo(35 / 300)
    expect(summary.rangeCoverage).toBe(0.5)
    expect(forecastBacktestSummary(result, true).typicalError).toBe(0.05)
  })
})
