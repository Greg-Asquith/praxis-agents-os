// apps/web/src/integrations/google_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/accounts-presenter"
import { googleAdsCampaignStatusPresenter } from "@/integrations/google_ads/campaign-status-presenter"
import { GoogleAdsLogo } from "@/integrations/google_ads/logo"
import { googleAdsReportPresenter } from "@/integrations/google_ads/report-presenter"

export default {
  catalogDescription: "Let agents manage and report on your ad accounts.",
  icons: { google_ads: GoogleAdsLogo },
  providerKey: "google_ads",
  toolRowPresenters: [
    googleAdsReportPresenter,
    googleAdsAccountsPresenter,
    googleAdsCampaignStatusPresenter,
  ],
} satisfies IntegrationUiModule
