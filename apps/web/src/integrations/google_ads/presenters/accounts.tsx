// apps/web/src/integrations/google_ads/presenters/accounts.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  GoogleAdsAccountHierarchy,
  type GoogleAdsAccount,
} from "@/integrations/google_ads/components/account-hierarchy"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const googleAdsAccountsPresenter: ToolRowPresenter = {
  key: "google-ads-list-accounts",
  matches: (activity) => activity.name === "google_ads_list_accounts",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>List Google Ads Accounts</GoogleAdsToolHeading>}
          label="Loading Google Ads accounts…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, accountsData)
    if (!fanOut) {
      return null
    }
    const { data: accountsByEntry, entries } = fanOut
    return (
      <div aria-label="Google Ads account hierarchy" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          entries={entries}
          emptyLabel="No Google Ads account contexts were available."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>List Google Ads Accounts</GoogleAdsToolHeading>}
        >
          {(_entry, index) => {
            const accounts = accountsByEntry[index]
            if (!accounts) {
              return null
            }
            return accounts.length > 0 ? (
              <GoogleAdsAccountHierarchy accounts={accounts} />
            ) : (
              <p className="text-muted-foreground py-4 text-center text-sm">
                No accounts were discovered.
              </p>
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function accountsData(value: unknown): GoogleAdsAccount[] | null {
  if (!isRecord(value) || !Array.isArray(value["accounts"])) {
    return null
  }
  const accounts: GoogleAdsAccount[] = []
  for (const item of value["accounts"]) {
    if (
      !isRecord(item) ||
      typeof item["customer_id"] !== "string" ||
      typeof item["display_name"] !== "string" ||
      (item["parent_customer_id"] !== null && typeof item["parent_customer_id"] !== "string") ||
      typeof item["manager"] !== "boolean" ||
      typeof item["currency_code"] !== "string" ||
      typeof item["status"] !== "string" ||
      typeof item["writable"] !== "boolean" ||
      typeof item["enabled"] !== "boolean"
    ) {
      return null
    }
    accounts.push({
      currencyCode: item["currency_code"],
      customerId: formatGoogleAdsAccountId(item["customer_id"]),
      displayName: item["display_name"],
      enabled: item["enabled"],
      manager: item["manager"],
      parentCustomerId: item["parent_customer_id"],
      status: item["status"],
      writable: item["writable"],
    })
  }
  return accounts
}
