import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import bigQueryModule from "@/integrations/bigquery"
import { bigQueryQueryPresenter } from "@/integrations/bigquery/presenters/query"
import { bigQuerySchemaPresenter } from "@/integrations/bigquery/presenters/schema"
import { bigQueryTablesPresenter } from "@/integrations/bigquery/presenters/tables"
import type { ToolActivity } from "@/integrations/contract"
import { integrationToolRowPresenters, loadIntegrationUiModules } from "@/integrations/registry"

describe("BigQuery tool presenters", () => {
  it("renders query rows with export controls and honest cap metadata", () => {
    const html = render(
      bigQueryQueryPresenter.render(
        props({
          id: "query-1",
          kind: "result",
          name: "bigquery_run_query",
          status: "completed",
          args: {
            query: "SELECT campaign_id, spend FROM `praxis-analytics.marketing.campaign_daily`",
          },
          result: {
            rows: [
              { campaign_id: "campaign-1", spend: "125.50" },
              { campaign_id: "campaign-2", spend: null },
            ],
            total_rows: 12,
            truncated: true,
            total_bytes_processed: 2048,
            cache_hit: false,
            row_filters_applied: true,
          },
        })
      )
    )

    expect(html).toContain("Run BigQuery Query")
    expect(html).toContain("Campaign Id")
    expect(html).toContain("campaign-1")
    expect(html).toContain("125.50")
    expect(html).toContain("Showing 2 of 12 rows.")
    expect(html).toContain("Download Report CSV")
    expect(html).toContain("Limited")
    expect(html).toContain("Row filters limited this result")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("renders all loading states and falls through for malformed results", () => {
    for (const [presenter, name, expected] of [
      [bigQueryTablesPresenter, "bigquery_list_tables", "Listing BigQuery tables"],
      [bigQuerySchemaPresenter, "bigquery_get_table_schema", "Reading BigQuery table schema"],
      [bigQueryQueryPresenter, "bigquery_run_query", "Running BigQuery query"],
    ] as const) {
      const html = render(
        presenter.render(
          props({
            id: name,
            kind: "call",
            name,
            status: "running",
          })
        )
      )
      expect(html).toContain(expected)
      expect(html).toContain("text-sm font-medium")
    }

    expect(
      bigQueryQueryPresenter.render(
        props({
          id: "bad-query",
          kind: "result",
          name: "bigquery_run_query",
          status: "completed",
          result: { rows: "invalid" },
        })
      )
    ).toBeNull()
  })

  it("loads all presenters and the icon through the production registry seam", async () => {
    expect(bigQueryModule.toolRowPresenters.map((presenter) => presenter.key)).toEqual([
      "bigquery_list_tables",
      "bigquery_get_table_schema",
      "bigquery_run_query",
    ])

    await loadIntegrationUiModules(["bigquery"])

    expect(integrationToolRowPresenters("bigquery").map((presenter) => presenter.key)).toEqual([
      "bigquery_list_tables",
      "bigquery_get_table_schema",
      "bigquery_run_query",
    ])
    const row = renderCustomToolCallRow(
      props({
        id: "registry-query",
        kind: "result",
        name: "bigquery_run_query",
        status: "completed",
        result: {
          rows: [],
          total_rows: 0,
          truncated: false,
          total_bytes_processed: 0,
          cache_hit: true,
        },
      })
    )
    expect(render(row)).toContain('aria-label="BigQuery query results"')
  })
})

function props(activity: ToolActivity) {
  return {
    activity,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "bigquery",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
