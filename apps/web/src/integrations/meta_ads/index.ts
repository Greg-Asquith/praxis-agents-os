// apps/web/src/integrations/meta_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MetaAdsConnectHelp } from "@/integrations/meta_ads/components/connect-help"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsCopyAdsPresenter } from "@/integrations/meta_ads/presenters/copy-ads"
import { metaAdsCreateAdSetPresenter } from "@/integrations/meta_ads/presenters/create-ad-set"
import { metaAdsCreateAdsPresenter } from "@/integrations/meta_ads/presenters/create-ads"
import { metaAdsCreateCampaignPresenter } from "@/integrations/meta_ads/presenters/create-campaign"
import { metaAdsActivitiesPresenter } from "@/integrations/meta_ads/presenters/activities"
import { metaAdsLaunchCampaignPresenter } from "@/integrations/meta_ads/presenters/launch-campaign"
import { metaAdsListAssetsPresenter } from "@/integrations/meta_ads/presenters/list-assets"
import { metaAdsSearchTargetingPresenter } from "@/integrations/meta_ads/presenters/search-targeting"
import { metaAdsEstimateAudiencePresenter } from "@/integrations/meta_ads/presenters/estimate-audience"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsConversionsPresenter } from "@/integrations/meta_ads/presenters/conversions"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"
import { metaAdsScheduleBudgetIncreasesPresenter } from "@/integrations/meta_ads/presenters/schedule-budget-increases"
import { metaAdsUpdateAdSetsPresenter } from "@/integrations/meta_ads/presenters/update-ad-sets"
import { metaAdsUpdateAdsPresenter } from "@/integrations/meta_ads/presenters/update-ads"
import { metaAdsUpdateBudgetsPresenter } from "@/integrations/meta_ads/presenters/update-budgets"
import { metaAdsUpdateCampaignsPresenter } from "@/integrations/meta_ads/presenters/update-campaigns"
import { metaAdsUpdateStatusPresenter } from "@/integrations/meta_ads/presenters/update-status"
import { metaAdsUpdateTargetingPresenter } from "@/integrations/meta_ads/presenters/update-targeting"
import { metaAdsUploadMediaPresenter } from "@/integrations/meta_ads/presenters/upload-media"

export default {
  catalogDescription:
    "Report on your Facebook and Instagram ads, and, with your approval, create, launch, and edit campaigns, ad sets, and ads, including budgets, bids, targeting, and status.",
  ConnectHelp: MetaAdsConnectHelp,
  credentialLabel: "Access token",
  Logo: MetaAdsLogo,
  providerKey: "meta_ads",
  toolRowPresenters: [
    metaAdsInsightsPresenter,
    metaAdsAccountsPresenter,
    metaAdsObjectsPresenter,
    metaAdsConversionsPresenter,
    metaAdsActivitiesPresenter,
    metaAdsListAssetsPresenter,
    metaAdsSearchTargetingPresenter,
    metaAdsEstimateAudiencePresenter,
    metaAdsUpdateStatusPresenter,
    metaAdsUpdateBudgetsPresenter,
    metaAdsScheduleBudgetIncreasesPresenter,
    metaAdsUpdateCampaignsPresenter,
    metaAdsUpdateAdSetsPresenter,
    metaAdsUpdateTargetingPresenter,
    metaAdsUpdateAdsPresenter,
    metaAdsUploadMediaPresenter,
    metaAdsCreateCampaignPresenter,
    metaAdsCreateAdSetPresenter,
    metaAdsCreateAdsPresenter,
    metaAdsLaunchCampaignPresenter,
    metaAdsCopyAdsPresenter,
  ],
} satisfies IntegrationUiModule
