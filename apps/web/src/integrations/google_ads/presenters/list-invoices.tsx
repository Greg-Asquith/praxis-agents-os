// apps/web/src/integrations/google_ads/presenters/list-invoices.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { GoogleAdsInvoicesTable } from "@/integrations/google_ads/components/invoices-table"
import { parseGoogleAdsInvoices } from "@/integrations/google_ads/lib/invoices"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, stringDetail } from "@/integrations/tool-details"

const NO_INVOICES = {
  listed: "Google issued no invoices to this account in these months.",
  manager_account: "Manager accounts get no invoices of their own. Select a client account.",
  not_monthly_invoicing:
    "This account isn't paid by monthly invoice, so Google Ads has no invoices for it.",
} as const

export const googleAdsListInvoicesPresenter = defineIntegrationReadPresenter(googleAdsProvider, {
  ariaLabel: "Google Ads invoices",
  emptyLabel: "No Google Ads accounts were queried.",
  heading: "List Invoices",
  progressLabel: "Listing invoices…",
  tool: "google_ads_list_invoices",
  details: (args) =>
    compactDetails([
      stringDetail(args, "start_month", "From"),
      stringDetail(args, "end_month", "To"),
    ]),
  parseResult: parseGoogleAdsInvoices,
  render: (result, _entry, _args, preview) =>
    result.invoices.length === 0 ? (
      <EmptyResult>{NO_INVOICES[result.state]}</EmptyResult>
    ) : (
      <GoogleAdsInvoicesTable preview={preview} result={result} />
    ),
})
