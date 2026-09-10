// apps/web/src/integrations/google_ads/provider.ts

import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"
import { formatGoogleAdsAccountId } from "@/lib/format"

export const googleAdsProvider: IntegrationProviderUi = {
  contextLabel: "Account",
  externalLabel: "Customer ID",
  fallbackDisplayName: "Selected Google Ads account",
  formatContextValue: formatGoogleAdsAccountId,
  Logo: GoogleAdsLogo,
  name: "Google Ads",
  providerKey: "google_ads",
}
