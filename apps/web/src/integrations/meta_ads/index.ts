// apps/web/src/integrations/meta_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MetaAdsConnectHelp } from "@/integrations/meta_ads/components/connect-help"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsActivitiesPresenter } from "@/integrations/meta_ads/presenters/activities"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsConversionsPresenter } from "@/integrations/meta_ads/presenters/conversions"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"

export default {
  catalogDescription:
    "Read performance, account status, budgets, custom conversions, custom events, and change history for your Facebook and Instagram ads.",
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
  ],
} satisfies IntegrationUiModule
