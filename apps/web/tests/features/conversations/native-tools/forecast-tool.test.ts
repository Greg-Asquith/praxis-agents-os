// apps/web/tests/features/conversations/native-tools/forecast-tool.test.ts

import { describe, expect, it } from "vitest"

import {
  forecastBacktestSummary,
  forecastToolResult,
} from "@/features/conversations/native-tools/forecast-tool"
import { forecastPublicResult } from "../../../support/forecast"

describe("forecastBacktestSummary", () => {
  it("reports the test results of the forecast on show", () => {
    const result = forecastToolResult(forecastPublicResult())
    if (!result) throw new Error("expected a forecast result")

    expect(forecastBacktestSummary(result, true).typicalError).toBe(0.05)
    expect(forecastBacktestSummary(result, false).typicalError).toBe(0.12)
    expect(forecastBacktestSummary(result, false).rangeCoverage).toBe(0.5)
  })
})
