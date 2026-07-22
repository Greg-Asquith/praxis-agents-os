// apps/web/src/integrations/google_ads/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/logo"

export default {
  catalogDescription: "Let agents manage and report on your ad accounts.",
  icons: { google_ads: GoogleAdsLogo },
  providerKey: "google_ads",
} satisfies IntegrationUiModule
