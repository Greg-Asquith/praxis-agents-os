import { createElement, type ComponentProps, type ReactElement } from "react"
import type { DataTable } from "@/components/ui/data-table"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { dataTableExport } from "@/components/ui/data-table-model"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"

const columns = [{ key: "campaign", label: "Campaign", kind: "text" as const }]
const rows: GoogleAdsOutcomeRow[] = [
  { campaign: "Brand", outcome: "updated" },
  { campaign: "Search", outcome: "already_set" },
  { campaign: "Shopping", outcome: "failed", details: "Bid rejected", errorCode: "TARGET_CPA" },
  { campaign: "Display", outcome: "unverified" },
]

function table(values = rows, truncated = false): ReactElement<ComponentProps<typeof DataTable>> {
  return GoogleAdsOutcomeTable({
    columns,
    rows: values,
    outcomes: countByKind(values).reverse(),
    exportFilename: "campaigns.csv",
    truncated,
  })
}

describe("Google Ads shared outcome kit", () => {
  it("keeps each aggregate error code readable in exports", () => {
    const rendered = table([
      { campaign: "Brand", outcome: "failed", errorCode: ["TARGET_CPA", "TARGET_ROAS"] },
    ])
    expect(renderToStaticMarkup(rendered)).toContain("Target CPA · Target ROAS")
    expect(dataTableExport(rendered.props.columns, rendered.props.rows).rows).toEqual([
      ["Brand", "Failed", "Target CPA · Target ROAS"],
    ])
  })

  it("adds only the evidence columns present in the result", () => {
    expect(
      table([{ campaign: "Brand", outcome: "updated" }]).props.columns.map((column) => column.label)
    ).toEqual(["Campaign", "Outcome"])
    expect(
      table([{ campaign: "Brand", outcome: "updated", details: "Observed" }]).props.columns.map(
        (column) => column.label
      )
    ).toEqual(["Campaign", "Outcome", "Details"])
    expect(
      table([{ campaign: "Brand", outcome: "failed" }]).props.columns.map((column) => column.label)
    ).toEqual(["Campaign", "Outcome", "Error code"])
  })

  it("exports tool columns and readable outcomes without internal display metadata", () => {
    const { props } = table()
    expect(props.exportFilename).toBe("campaigns.csv")
    expect(dataTableExport(props.columns, props.rows)).toEqual({
      headers: ["Campaign", "Outcome", "Details", "Error code"],
      rows: [
        ["Brand", "Updated", "", ""],
        ["Search", "Already set", "", ""],
        ["Shopping", "Failed", "Bid rejected", "Target CPA"],
        ["Display", "Unverified", "", ""],
      ],
    })
  })

  it("renders escaped target labels as chips and handles missing targets", () => {
    const html = renderToStaticMarkup(
      createElement(GoogleAdsFailureTargets, {
        description: "No change confirmed.",
        targets: ["Brand", "123", "<script>", "Brand"],
      })
    )
    expect(html.match(/data-slot="badge"/g)).toHaveLength(3)
    expect(html).toContain("&lt;script&gt;")
    expect(html).toContain(">123<")
    expect(
      renderToStaticMarkup(
        createElement(GoogleAdsFailureTargets, { description: "No change confirmed.", targets: [] })
      )
    ).not.toContain('data-slot="badge"')
  })
})
