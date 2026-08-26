import { describe, expect, it } from "vitest"

import { planBulkToolModes } from "@/features/agents/components/agent-tool-catalog-utils"
import type { ToolCatalogEntry } from "@/features/tools/types"

const readTool: ToolCatalogEntry = {
  default_policy: "auto",
  defer_loading: false,
  description: "Run a report.",
  effect: "read",
  effect_scope: "external",
  egress: "none",
  kind: "function",
  label: "Run Report",
  name: "ads_run_report",
  provider: "google_ads",
  supported_policies: ["auto", "approval"],
}

const writeTool: ToolCatalogEntry = {
  ...readTool,
  default_policy: "approval",
  description: "Apply recommendations.",
  effect: "write",
  egress: "external_write",
  label: "Apply Recommendations",
  name: "ads_apply_recommendations",
  supported_policies: ["approval"],
}

describe("planBulkToolModes", () => {
  it("turns every tool off", () => {
    const plan = planBulkToolModes([readTool, writeTool], "off")

    expect(plan.modes).toEqual({ ads_run_report: "off", ads_apply_recommendations: "off" })
    expect(plan.autoCount).toBe(0)
    expect(plan.approvalCount).toBe(0)
  })

  it("uses auto where supported and approval for the rest", () => {
    const plan = planBulkToolModes([readTool, writeTool], "auto")

    expect(plan.modes).toEqual({ ads_run_report: "auto", ads_apply_recommendations: "approval" })
    expect(plan.autoCount).toBe(1)
    expect(plan.approvalCount).toBe(1)
  })

  it("sets approval on every tool that supports it", () => {
    const plan = planBulkToolModes([readTool, writeTool], "approval")

    expect(plan.modes).toEqual({
      ads_run_report: "approval",
      ads_apply_recommendations: "approval",
    })
    expect(plan.approvalCount).toBe(2)
  })

  it("leaves a tool unchanged when it supports neither target", () => {
    const plan = planBulkToolModes([{ ...readTool, supported_policies: [] }], "auto")

    expect(plan.modes).toEqual({})
  })
})
