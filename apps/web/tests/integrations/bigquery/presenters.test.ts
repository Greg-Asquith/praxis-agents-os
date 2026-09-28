import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { bigQueryQueryPresenter } from "@/integrations/bigquery/presenters/query"
import type { ToolActivity } from "@/integrations/contract"

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

    expect(html).toContain("campaign-1")
    expect(html).toContain("Showing 2 of 12 rows.")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("falls through for malformed results", () => {
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
