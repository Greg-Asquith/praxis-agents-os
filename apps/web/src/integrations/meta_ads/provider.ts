// apps/web/src/integrations/meta_ads/provider.ts

import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const metaAdsProvider: IntegrationProviderUi = {
  contextLabel: "Ad account",
  externalLabel: "Account ID",
  fallbackDisplayName: "Selected Meta Ads account",
  Logo: MetaAdsLogo,
  name: "Meta Ads",
  providerKey: "meta_ads",
}
