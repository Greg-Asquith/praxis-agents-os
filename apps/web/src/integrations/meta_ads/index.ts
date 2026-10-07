// apps/web/src/integrations/meta_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MetaAdsConnectHelp } from "@/integrations/meta_ads/components/connect-help"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsActivitiesPresenter } from "@/integrations/meta_ads/presenters/activities"
import { metaAdsListAssetsPresenter } from "@/integrations/meta_ads/presenters/list-assets"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsConversionsPresenter } from "@/integrations/meta_ads/presenters/conversions"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"
import { metaAdsUpdateBudgetsPresenter } from "@/integrations/meta_ads/presenters/update-budgets"
import { metaAdsUpdateStatusPresenter } from "@/integrations/meta_ads/presenters/update-status"
import { metaAdsUploadMediaPresenter } from "@/integrations/meta_ads/presenters/upload-media"

export default {
  catalogDescription:
    "Read performance, account status, budgets, custom conversions, custom events, and change history for your Facebook and Instagram ads, see the Pages, Instagram accounts, and media you can advertise with, and, with your approval, upload images and videos, turn campaigns, ad sets, and ads on or off, and change budgets.",
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
    metaAdsUpdateStatusPresenter,
    metaAdsUpdateBudgetsPresenter,
    metaAdsUploadMediaPresenter,
  ],
} satisfies IntegrationUiModule
