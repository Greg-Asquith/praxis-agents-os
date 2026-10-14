// apps/web/src/integrations/meta_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MetaAdsConnectHelp } from "@/integrations/meta_ads/components/connect-help"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsCopyAdsPresenter } from "@/integrations/meta_ads/presenters/copy-ads"
import { metaAdsCreateAdSetPresenter } from "@/integrations/meta_ads/presenters/create-ad-set"
import { metaAdsCreateAdsPresenter } from "@/integrations/meta_ads/presenters/create-ads"
import { metaAdsActivitiesPresenter } from "@/integrations/meta_ads/presenters/activities"
import { metaAdsListAssetsPresenter } from "@/integrations/meta_ads/presenters/list-assets"
import { metaAdsSearchTargetingPresenter } from "@/integrations/meta_ads/presenters/search-targeting"
import { metaAdsEstimateAudiencePresenter } from "@/integrations/meta_ads/presenters/estimate-audience"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsConversionsPresenter } from "@/integrations/meta_ads/presenters/conversions"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"
import { metaAdsUpdateBudgetsPresenter } from "@/integrations/meta_ads/presenters/update-budgets"
import { metaAdsUpdateStatusPresenter } from "@/integrations/meta_ads/presenters/update-status"
import { metaAdsUploadMediaPresenter } from "@/integrations/meta_ads/presenters/upload-media"

export default {
  catalogDescription:
    "Read performance, account status, budgets, custom conversions, custom events, and change history for your Facebook and Instagram ads, see the Pages, Instagram accounts, and media you can advertise with, find targeting options and estimate audience sizes, and, with your approval, upload images and videos, create paused ad sets in existing campaigns, create image, video, and carousel ads in existing ad sets with every Meta advanced setting and AI enhancement off unless you turn it on, copy existing ads into other ad sets, turn campaigns, ad sets, and ads on or off, and change budgets.",
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
    metaAdsUploadMediaPresenter,
    metaAdsCreateAdSetPresenter,
    metaAdsCreateAdsPresenter,
    metaAdsCopyAdsPresenter,
  ],
} satisfies IntegrationUiModule
