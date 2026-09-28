// apps/web/src/integrations/meta_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MetaAdsConnectHelp } from "@/integrations/meta_ads/components/connect-help"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsActivitiesPresenter } from "@/integrations/meta_ads/presenters/activities"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsCustomConversionsPresenter } from "@/integrations/meta_ads/presenters/custom-conversions"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"

export default {
  catalogDescription:
    "Read performance, account status, budgets, custom conversions, and change history for your Facebook and Instagram ads.",
  ConnectHelp: MetaAdsConnectHelp,
  credentialLabel: "Access token",
  Logo: MetaAdsLogo,
  providerKey: "meta_ads",
  toolRowPresenters: [
    metaAdsInsightsPresenter,
    metaAdsAccountsPresenter,
    metaAdsObjectsPresenter,
    metaAdsCustomConversionsPresenter,
    metaAdsActivitiesPresenter,
  ],
} satisfies IntegrationUiModule
