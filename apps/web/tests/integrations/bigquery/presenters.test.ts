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
  it("renders datasets and cached tables as a scannable inventory", () => {
    const html = render(
      bigQueryTablesPresenter.render(
        props({
          id: "tables-1",
          kind: "result",
          name: "bigquery_list_tables",
          status: "completed",
          result: {
            datasets: [
              {
                dataset: "praxis-analytics.marketing",
                display_name: "Marketing",
                tables: [
                  {
                    table: "campaign_daily",
                    table_type: "table",
                    description: "Daily campaign performance.",
                    row_count: 12500,
                    last_synced_at: "2026-07-28T10:00:00Z",
                  },
                ],
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("List BigQuery Tables")
    expect(html).toContain("Marketing")
    expect(html).toContain("praxis-analytics.marketing")
    expect(html).toContain("campaign_daily")
    expect(html).toContain("Daily campaign performance.")
    expect(html).toMatch(/12,?500 rows/)
  })

  it("renders schema metadata and makes partition requirements prominent", () => {
    const html = render(
      bigQuerySchemaPresenter.render(
        props({
          id: "schema-1",
          kind: "result",
          name: "bigquery_get_table_schema",
          status: "completed",
          result: {
            table: "`praxis-analytics.marketing.campaign_daily`",
            table_type: "partitioned_table",
            description: "Daily campaign performance.",
            fields: [
              {
                name: "campaign.id",
                type: "STRING",
                mode: "REQUIRED",
                description: "Stable campaign identifier.",
              },
              {
                name: "spend",
                type: "NUMERIC",
                mode: "NULLABLE",
                description: null,
              },
            ],
            partitioning: {
              field: "report_date",
              require_partition_filter: true,
              type: "DAY",
            },
            clustering_fields: ["account_id"],
            row_count: 12500,
            size_bytes: 4096,
            last_synced_at: "2026-07-28T10:00:00Z",
            requires_partition_filter: true,
          },
        })
      )
    )

    expect(html).toContain("Get BigQuery Table Schema")
    expect(html).toContain("Partition filter required")
    expect(html).toContain("Clustered by account_id")
    expect(html).toContain("campaign.id")
    expect(html).toContain("Stable campaign identifier.")
    expect(html).toContain("STRING")
    expect(html).toContain("REQUIRED")
    expect(html).toContain("4.0 KB")
  })

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
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("explains when the structured result limit excludes every row", () => {
    const html = render(
      bigQueryQueryPresenter.render(
        props({
          id: "query-limited",
          kind: "result",
          name: "bigquery_run_query",
          status: "completed",
          result: {
            rows: [],
            total_rows: 1,
            truncated: true,
            total_bytes_processed: 1,
            cache_hit: false,
          },
        })
      )
    )

    expect(html).toContain("The result exceeded the safe output limit")
    expect(html).not.toContain("The query returned no rows.")
  })

  it("renders all loading states and falls through for malformed results", () => {
    for (const [presenter, name, expected] of [
      [bigQueryTablesPresenter, "bigquery_list_tables", "Listing BigQuery tables"],
      [bigQuerySchemaPresenter, "bigquery_get_table_schema", "Reading BigQuery table schema"],
      [bigQueryQueryPresenter, "bigquery_run_query", "Running BigQuery query"],
    ] as const) {
      expect(
        render(
          presenter.render(
            props({
              id: name,
              kind: "call",
              name,
              status: "running",
            })
          )
        )
      ).toContain(expected)
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
      "bigquery-list-tables",
      "bigquery-get-table-schema",
      "bigquery-run-query",
    ])

    await loadIntegrationUiModules(["bigquery"])

    expect(integrationToolRowPresenters("bigquery").map((presenter) => presenter.key)).toEqual([
      "bigquery-list-tables",
      "bigquery-get-table-schema",
      "bigquery-run-query",
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
