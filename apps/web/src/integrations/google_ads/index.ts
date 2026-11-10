// apps/web/src/integrations/google_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsUpdateStatusPresenter } from "@/integrations/google_ads/presenters/update-status"
import { googleAdsUpdateCampaignsPresenter } from "@/integrations/google_ads/presenters/update-campaigns"
import { googleAdsSearchTargetingPresenter } from "@/integrations/google_ads/presenters/search-targeting"
import { googleAdsUpdateTargetingPresenter } from "@/integrations/google_ads/presenters/update-targeting"
import { googleAdsCreateAdsPresenter } from "@/integrations/google_ads/presenters/create-ads"
import { googleAdsCreateAdGroupsPresenter } from "@/integrations/google_ads/presenters/create-ad-groups"
import { googleAdsCreateCampaignPresenter } from "@/integrations/google_ads/presenters/create-campaign"
import { googleAdsDeviceBidModifiersPresenter } from "@/integrations/google_ads/presenters/device-bid-modifiers"
import { googleAdsApplyRecommendationsPresenter } from "@/integrations/google_ads/presenters/apply-recommendations"
import { googleAdsCreatePositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/create-positive-keywords"
import { googleAdsDismissRecommendationsPresenter } from "@/integrations/google_ads/presenters/dismiss-recommendations"
import { googleAdsAssignCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/assign-campaign-budgets"
import { googleAdsCreateLabelsPresenter } from "@/integrations/google_ads/presenters/create-labels"
import { googleAdsLabelAssociationsPresenter } from "@/integrations/google_ads/presenters/label-associations"
import { googleAdsDeleteLabelsPresenter } from "@/integrations/google_ads/presenters/delete-labels"
import { googleAdsCreateCampaignBudgetPresenter } from "@/integrations/google_ads/presenters/create-campaign-budget"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { googleAdsUpdateNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/update-negative-keywords"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { googleAdsReportFieldsPresenter } from "@/integrations/google_ads/presenters/report-fields"
import { googleAdsRemoveCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/remove-campaign-budgets"
import { googleAdsUpdateCampaignBudgetAmountsPresenter } from "@/integrations/google_ads/presenters/update-campaign-budget-amounts"
import { googleAdsRemovePositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/remove-positive-keywords"
import { googleAdsUpdatePositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/update-positive-keywords"

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
    googleAdsDeleteLabelsPresenter,
    googleAdsUpdateNegativeKeywordsPresenter,
    googleAdsUpdateStatusPresenter,
    googleAdsUpdateCampaignsPresenter,
    googleAdsSearchTargetingPresenter,
    googleAdsUpdateTargetingPresenter,
    googleAdsCreateAdsPresenter,
    googleAdsCreateAdGroupsPresenter,
    googleAdsCreateCampaignPresenter,
    googleAdsDeviceBidModifiersPresenter,
    googleAdsApplyRecommendationsPresenter,
    googleAdsDismissRecommendationsPresenter,
    googleAdsCreatePositiveKeywordsPresenter,
    googleAdsCreateCampaignBudgetPresenter,
    googleAdsUpdateCampaignBudgetAmountsPresenter,
    googleAdsUpdatePositiveKeywordsPresenter,
    googleAdsRemovePositiveKeywordsPresenter,
    googleAdsAssignCampaignBudgetsPresenter,
    googleAdsRemoveCampaignBudgetsPresenter,
  ],
} satisfies IntegrationUiModule
