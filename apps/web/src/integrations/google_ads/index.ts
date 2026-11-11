// apps/web/src/integrations/google_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsUpdateStatusPresenter } from "@/integrations/google_ads/presenters/update-status"
import { googleAdsUpdateCampaignsPresenter } from "@/integrations/google_ads/presenters/update-campaigns"
import { googleAdsUpdateAdsPresenter } from "@/integrations/google_ads/presenters/update-ads"
import { googleAdsUpdateAdGroupsPresenter } from "@/integrations/google_ads/presenters/update-ad-groups"
import { googleAdsUpdateBudgetsPresenter } from "@/integrations/google_ads/presenters/update-budgets"
import { googleAdsSearchTargetingPresenter } from "@/integrations/google_ads/presenters/search-targeting"
import { googleAdsUpdateTargetingPresenter } from "@/integrations/google_ads/presenters/update-targeting"
import { googleAdsCreateAdsPresenter } from "@/integrations/google_ads/presenters/create-ads"
import { googleAdsCreateAdGroupsPresenter } from "@/integrations/google_ads/presenters/create-ad-groups"
import { googleAdsCreateCampaignPresenter } from "@/integrations/google_ads/presenters/create-campaign"
import { googleAdsApplyRecommendationsPresenter } from "@/integrations/google_ads/presenters/apply-recommendations"
import { googleAdsCreateKeywordsPresenter } from "@/integrations/google_ads/presenters/create-keywords"
import { googleAdsDismissRecommendationsPresenter } from "@/integrations/google_ads/presenters/dismiss-recommendations"
import { googleAdsCreateLabelsPresenter } from "@/integrations/google_ads/presenters/create-labels"
import { googleAdsLabelAssociationsPresenter } from "@/integrations/google_ads/presenters/label-associations"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { googleAdsUpdateNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/update-negative-keywords"
import { googleAdsOptimiseSearchTermsPresenter } from "@/integrations/google_ads/presenters/optimise-search-terms"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { googleAdsReportFieldsPresenter } from "@/integrations/google_ads/presenters/report-fields"
import { googleAdsRemoveObjectsPresenter } from "@/integrations/google_ads/presenters/remove-objects"
import { googleAdsUpdateKeywordsPresenter } from "@/integrations/google_ads/presenters/update-keywords"

export default {
  catalogDescription: "Let agents manage and report on your ad accounts.",
  Logo: GoogleAdsLogo,
  providerKey: "google_ads",
  toolRowPresenters: [
    googleAdsReportPresenter,
    googleAdsReportFieldsPresenter,
    googleAdsAccountsPresenter,
    googleAdsCreateLabelsPresenter,
    googleAdsLabelAssociationsPresenter,
    googleAdsUpdateNegativeKeywordsPresenter,
    googleAdsOptimiseSearchTermsPresenter,
    googleAdsUpdateStatusPresenter,
    googleAdsUpdateCampaignsPresenter,
    googleAdsUpdateAdsPresenter,
    googleAdsUpdateAdGroupsPresenter,
    googleAdsSearchTargetingPresenter,
    googleAdsUpdateTargetingPresenter,
    googleAdsCreateAdsPresenter,
    googleAdsCreateAdGroupsPresenter,
    googleAdsCreateCampaignPresenter,
    googleAdsApplyRecommendationsPresenter,
    googleAdsDismissRecommendationsPresenter,
    googleAdsCreateKeywordsPresenter,
    googleAdsUpdateBudgetsPresenter,
    googleAdsUpdateKeywordsPresenter,
    googleAdsRemoveObjectsPresenter,
  ],
} satisfies IntegrationUiModule
