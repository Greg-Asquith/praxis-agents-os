// apps/web/src/integrations/google_ads/presenters/accounts.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { GoogleAdsAccountHierarchy } from "@/integrations/google_ads/components/account-hierarchy"
import { parseGoogleAdsAccounts } from "@/integrations/google_ads/lib/accounts"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAdsAccountsPresenter = defineIntegrationReadPresenter(googleAdsProvider, {
  ariaLabel: "Google Ads account hierarchy",
  emptyLabel: "No Google Ads account contexts were available.",
  heading: "List Google Ads Accounts",
  parseResult: parseGoogleAdsAccounts,
  progressLabel: "Loading Google Ads accounts…",
  render: (accounts) =>
    accounts.length > 0 ? (
      <GoogleAdsAccountHierarchy accounts={accounts} />
    ) : (
      <EmptyResult>No accounts were discovered.</EmptyResult>
    ),
  tool: "google_ads_list_accounts",
})
