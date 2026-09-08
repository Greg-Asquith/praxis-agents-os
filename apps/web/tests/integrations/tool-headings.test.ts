import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { AirtableToolHeading } from "@/integrations/airtable/components/tool-heading"
import { BigQueryToolHeading } from "@/integrations/bigquery/components/tool-heading"
import { GmailToolHeading } from "@/integrations/gmail/components/tool-heading"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { GoogleAnalyticsToolHeading } from "@/integrations/google_analytics/components/tool-heading"
import { OutlookToolHeading } from "@/integrations/outlook_mail/components/tool-heading"

describe("integration tool headings", () => {
  it.each([
    ["Airtable", createElement(AirtableToolHeading, null, "Loading Airtable")],
    ["BigQuery", createElement(BigQueryToolHeading, null, "Loading BigQuery")],
    ["Gmail", createElement(GmailToolHeading, null, "Loading Gmail")],
    ["Google Ads", createElement(GoogleAdsToolHeading, null, "Loading Google Ads")],
    [
      "Google Analytics",
      createElement(GoogleAnalyticsToolHeading, null, "Loading Google Analytics"),
    ],
    ["Outlook", createElement(OutlookToolHeading, null, "Loading Outlook")],
  ])("keeps %s headings compact outside a result-card header", (_provider, heading) => {
    const html = render(heading)

    expect(html).toContain("text-sm")
    expect(html).toContain("font-medium")
  })
})

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
