// apps/web/tests/features/conversations/components/forecast-tool-presenter.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ForecastChart } from "@/features/conversations/components/forecast-chart"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { forecastToolResult } from "@/features/conversations/native-tools/forecast-tool"
import { forecastPublicResult } from "../../../support/forecast"

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters: () => [] }))

describe("forecast tool row", () => {
  it("renders a running call and a completed forecast as forecast cards", () => {
    const running = render({ status: "running" })
    const completed = render({ status: "completed", result: forecastPublicResult() })

    expect(running).toContain('aria-busy="true"')
    expect(completed).toContain('data-slot="tool-result-card"')
  })

  it("shows caveats only when the forecast has them", () => {
    const clear = { ...forecastPublicResult(), caveats: [] }

    expect(render({ status: "completed", result: forecastPublicResult() })).toContain(
      'role="alert"'
    )
    expect(render({ status: "completed", result: clear })).not.toContain('role="alert"')
  })

  it("leaves failed calls and malformed results to the default row", () => {
    const malformed = forecastPublicResult()
    malformed.chart.history.pop()

    expect(row({ status: "failed", result: "The service is unavailable." })).toBeNull()
    expect(row({ status: "completed", result: malformed })).toBeNull()
  })

  it("offers the covariate switch only when a forecast without covariates exists", () => {
    expect(chart(forecastPublicResult())).toContain('role="switch"')
    expect(chart(forecastPublicResult({ baseline: false }))).not.toContain('role="switch"')
  })
})

function row(activity: Pick<ToolActivity, "status" | "result">) {
  return renderCustomToolCallRow({
    activity: { id: "call-1", kind: "result", name: "forecast_series", ...activity },
    compact: false,
    defaultOpen: false,
    label: "Forecast Series",
    live: false,
    providerKey: "core",
    ui: null,
  })
}

function render(activity: Pick<ToolActivity, "status" | "result">) {
  return renderToStaticMarkup(row(activity))
}

function chart(value: unknown) {
  const result = forecastToolResult(value)
  if (!result) throw new Error("expected a forecast result")
  return renderToStaticMarkup(
    createElement(ForecastChart, { result, useCovariates: true, onUseCovariatesChange: vi.fn() })
  )
}
