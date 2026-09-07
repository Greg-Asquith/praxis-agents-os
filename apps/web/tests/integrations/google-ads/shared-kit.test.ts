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
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsBeforeAfter } from "@/integrations/google_ads/components/before-after"
import {
  GoogleAdsEntityCard,
  GoogleAdsEntityGroup,
} from "@/integrations/google_ads/components/entity-card"

describe("Google Ads shared approval kit", () => {
  it.each(["neutral", "destructive"] as const)("renders a labelled %s section", (tone) => {
    const html = renderToStaticMarkup(
      createElement(GoogleAdsApprovalSection, {
        ariaLabel: "Proposed changes",
        title: "Search",
        countLine: "2 campaigns",
        tone,
        children: "Review the selected campaigns.",
      })
    )
    expect(html).toContain('aria-label="Proposed changes"')
    expect(html).toContain(">Search<")
    expect(html).toContain(">2 campaigns<")
    expect(html).toContain("Review the selected campaigns.")
    if (tone === "destructive") {
      expect(html).toContain("border-destructive/35")
      expect(html).toContain("This action cannot be undone.")
    } else {
      expect(html).toContain("border-border bg-muted/35")
      expect(html).not.toContain("cannot be undone")
    }
  })

  it("keeps entity context and escapes retained labels inside groups", () => {
    const html = renderToStaticMarkup(
      createElement(GoogleAdsEntityGroup, {
        title: "Campaign <script>",
        meta: "UK account · GBP",
        children: createElement(GoogleAdsEntityCard, {
          title: "Brand & Search",
          meta: "Ad group",
          trailing: "2 keywords",
        }),
      })
    )
    expect(html).toContain("Campaign &lt;script&gt;")
    expect(html).toContain("UK account · GBP")
    expect(html).toContain("Brand &amp; Search")
    expect(html).toContain("Ad group")
    expect(html).toContain("2 keywords")
    expect(html).toContain("wrap-anywhere")
  })

  it("labels current and proposed values and accepts an accessible editor", () => {
    const html = renderToStaticMarkup(
      createElement(GoogleAdsBeforeAfter, {
        ariaLabel: "Keyword status",
        current: "Paused",
        proposed: createElement(
          "select",
          { "aria-label": "Proposed status", disabled: true },
          createElement("option", { value: "ENABLED" }, "Enabled")
        ),
      })
    )
    expect(html).toContain('aria-label="Keyword status" role="group"')
    expect(html).toContain(">Current<")
    expect(html).toContain(">Paused<")
    expect(html).toContain(">Proposed<")
    expect(html).toContain('<select aria-label="Proposed status" disabled="">')
    expect(html).toContain('aria-hidden="true"')
  })
})

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

  it.each([
    ["already_dismissed", "Already dismissed"],
    ["skipped_existing", "Already existed"],
    ["not_found", "Not found"],
  ] as const)("renders %s as a neutral skipped outcome", (outcome, label) => {
    const rendered = table([{ campaign: "Brand", outcome }])
    expect(renderToStaticMarkup(rendered)).toMatch(
      new RegExp(`data-variant="secondary"[^>]*>${label}`)
    )
    expect(dataTableExport(rendered.props.columns, rendered.props.rows).rows).toEqual([
      ["Brand", label],
    ])
  })

  it("orders stats by outcome kind and reserves warning for unverified writes", () => {
    const html = renderToStaticMarkup(table())
    const stats =
      html.match(
        /data-slot="stat"[\s\S]*?(?=<div data-slot="stat"|<\/div><\/div><\/div><div class="flex shrink)/g
      ) ?? []
    expect(stats).toHaveLength(4)
    for (const [index, label] of ["Applied", "Skipped", "Failed", "Unverified"].entries())
      expect(stats[index]).toContain(label)
    expect(stats[0]).toContain("text-success")
    expect(stats[1]).not.toMatch(/text-(success|warning|destructive)/)
    expect(stats[2]).toContain("text-destructive")
    expect(stats[3]).toContain("text-warning")
    expect(html).toMatch(/data-variant="secondary"[^>]*>Already set/)
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

  it("uses one sample note and retains custom tool cells", () => {
    expect(renderToStaticMarkup(table(rows, true))).toContain(
      "Showing a representative sample. Complete evidence is in the Audit Log."
    )
    expect(renderToStaticMarkup(table())).not.toContain("representative sample")
    const rendered = GoogleAdsOutcomeTable({
      columns,
      rows,
      outcomes: countByKind(rows),
      exportFilename: "campaigns.csv",
      renderCell: (column) =>
        column.key === "campaign" ? createElement("strong", null, "Custom campaign") : null,
    })
    expect(renderToStaticMarkup(rendered)).toContain("<strong>Custom campaign</strong>")
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
