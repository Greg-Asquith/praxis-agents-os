// apps/web/src/integrations/google_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsCampaignStatusPresenter } from "@/integrations/google_ads/presenters/campaign-status"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"

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
