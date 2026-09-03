// apps/web/src/integrations/google_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsCampaignStatusPresenter } from "@/integrations/google_ads/presenters/campaign-status"
import { googleAdsCampaignLinksPresenter } from "@/integrations/google_ads/presenters/campaign-links"
import { googleAdsDeviceBidModifiersPresenter } from "@/integrations/google_ads/presenters/device-bid-modifiers"
import { googleAdsApplyRecommendationsPresenter } from "@/integrations/google_ads/presenters/apply-recommendations"
import { googleAdsAddPositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/add-positive-keywords"
import { googleAdsDismissRecommendationsPresenter } from "@/integrations/google_ads/presenters/dismiss-recommendations"
import { googleAdsAssignCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/assign-campaign-budgets"
import { googleAdsCreateCampaignBudgetPresenter } from "@/integrations/google_ads/presenters/create-campaign-budget"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { googleAdsNegativeKeywordListsPresenter } from "@/integrations/google_ads/presenters/negative-keyword-lists"
import { googleAdsNegativeKeywordsPresenters } from "@/integrations/google_ads/presenters/negative-keywords"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { googleAdsReportFieldsPresenter } from "@/integrations/google_ads/presenters/report-fields"
import { googleAdsRemoveCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/remove-campaign-budgets"
import { googleAdsUpdateCampaignBudgetAmountsPresenter } from "@/integrations/google_ads/presenters/update-campaign-budget-amounts"

export default {
  catalogDescription: "Let agents manage and report on your ad accounts.",
  icons: { google_ads: GoogleAdsLogo },
  providerKey: "google_ads",
  toolRowPresenters: [
    googleAdsReportPresenter,
    googleAdsReportFieldsPresenter,
    googleAdsAccountsPresenter,
    googleAdsNegativeKeywordListsPresenter,
    ...googleAdsNegativeKeywordsPresenters,
    googleAdsCampaignLinksPresenter,
    googleAdsCampaignStatusPresenter,
    googleAdsDeviceBidModifiersPresenter,
    googleAdsApplyRecommendationsPresenter,
    googleAdsDismissRecommendationsPresenter,
    googleAdsAddPositiveKeywordsPresenter,
    googleAdsCreateCampaignBudgetPresenter,
    googleAdsUpdateCampaignBudgetAmountsPresenter,
    googleAdsAssignCampaignBudgetsPresenter,
    googleAdsRemoveCampaignBudgetsPresenter,
  ],
} satisfies IntegrationUiModule
