// apps/web/src/integrations/google_ads/presenters/accounts.tsx

import { fanOutEntries } from "@/components/tool-ui/fan-out"
import {
  GoogleAdsAccountsTable,
  type GoogleAdsAccountFailure,
} from "@/integrations/google_ads/components/accounts-table"
import {
  parseGoogleAdsAccountOverview,
  type GoogleAdsAccountOverview,
} from "@/integrations/google_ads/lib/accounts"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import { defineIntegrationResultPresenter } from "@/integrations/read-presenter"

type AccountsResult = {
  accounts: GoogleAdsAccountOverview[]
  failures: GoogleAdsAccountFailure[]
}

export const googleAdsAccountsPresenter = defineIntegrationResultPresenter(googleAdsProvider, {
  ariaLabel: "Google Ads accounts",
  details: (result) => [{ label: "Accounts", value: String(result.accounts.length) }],
  heading: "Get Google Ads Accounts",
  parseResult: parseAccountsResult,
  progressLabel: "Reading Google Ads accounts…",
  render: (result) => (
    <GoogleAdsAccountsTable accounts={result.accounts} failures={result.failures} />
  ),
  tool: "google_ads_get_accounts",
})

function parseAccountsResult(value: unknown): AccountsResult | null {
  const entries = fanOutEntries(value)
  if (!entries) return null
  const accounts: GoogleAdsAccountOverview[] = []
  const failures: GoogleAdsAccountFailure[] = []
  for (const entry of entries) {
    if (entry.status !== "success") {
      failures.push({
        displayName: entry.displayName,
        message: entry.errorMessage ?? "Google Ads returned an error.",
      })
      continue
    }
    const account = parseGoogleAdsAccountOverview(entry.data)
    if (!account) return null
    accounts.push(account)
  }
  return { accounts, failures }
}
