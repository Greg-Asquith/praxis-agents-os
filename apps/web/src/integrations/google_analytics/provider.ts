// apps/web/src/integrations/google_analytics/provider.ts

import { GoogleAnalyticsLogo } from "@/integrations/google_analytics/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const googleAnalyticsProvider: IntegrationProviderUi = {
  contextLabel: "Property",
  externalLabel: "Property ID",
  fallbackDisplayName: "Selected Google Analytics property",
  Logo: GoogleAnalyticsLogo,
  name: "Google Analytics",
  providerKey: "google_analytics",
}
