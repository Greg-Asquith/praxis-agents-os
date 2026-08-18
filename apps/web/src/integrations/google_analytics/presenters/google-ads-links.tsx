// apps/web/src/integrations/google_analytics/presenters/google-ads-links.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import {
  GoogleAnalyticsGoogleAdsLinksTable,
  type GoogleAdsLink,
} from "@/integrations/google_analytics/components/google-ads-links-table"
import { GoogleAnalyticsToolHeading } from "@/integrations/google_analytics/components/tool-heading"
import type { ToolRowPresenter } from "@/integrations/contract"
import { isRecord } from "@/lib/guards"

type GoogleAdsLinks = {
  links: GoogleAdsLink[]
}

const CUSTOMER_ID_PATTERN = /^\d{1,32}$/

export const googleAdsLinksPresenter: ToolRowPresenter = {
  key: "google-analytics-list-google-ads-links",
  matches: (activity) => activity.name === "google_analytics_list_google_ads_links",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleAnalyticsToolHeading>List Linked Google Ads Accounts</GoogleAnalyticsToolHeading>
          }
          label="Listing linked Google Ads accounts…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseGoogleAdsLinks)
    if (!fanOut) return null
    return (
      <div aria-label="Linked Google Ads accounts" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Property"
          defaultOpen={defaultOpen}
          emptyLabel="No Google Analytics properties were queried."
          externalLabel="Property ID"
          entries={fanOut.entries}
          heading={
            <GoogleAnalyticsToolHeading>List Linked Google Ads Accounts</GoogleAnalyticsToolHeading>
          }
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            if (!result) return null
            if (result.links.length === 0) {
              return (
                <p className="text-muted-foreground py-3 text-sm">
                  No Google Ads accounts are linked to this property.
                </p>
              )
            }
            return <GoogleAnalyticsGoogleAdsLinksTable links={result.links} />
          }}
        </FanOutShell>
      </div>
    )
  },
}

function parseGoogleAdsLinks(value: unknown): GoogleAdsLinks | null {
  if (!isRecord(value) || !Array.isArray(value["links"]) || !isCount(value["link_count"])) {
    return null
  }
  const links: GoogleAdsLink[] = []
  for (const item of value["links"]) {
    if (
      !isRecord(item) ||
      typeof item["customer_id"] !== "string" ||
      !CUSTOMER_ID_PATTERN.test(item["customer_id"]) ||
      typeof item["can_manage_clients"] !== "boolean" ||
      typeof item["ads_personalization_enabled"] !== "boolean" ||
      !isCreatedAt(item["created_at"])
    ) {
      return null
    }
    links.push({
      adsPersonalizationEnabled: item["ads_personalization_enabled"],
      canManageClients: item["can_manage_clients"],
      createdAt: item["created_at"],
      customerId: item["customer_id"],
    })
  }
  return value["link_count"] === links.length ? { links } : null
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

function isCreatedAt(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && !Number.isNaN(Date.parse(value)))
}
