// apps/web/src/integrations/google_analytics/index.ts

import { GoogleAnalyticsConnectHelp } from "@/integrations/google_analytics/components/connect-help"
import { GoogleAnalyticsLogo } from "@/integrations/google_analytics/components/logo"
import type { IntegrationUiModule } from "@/integrations/contract"

export default {
  catalogDescription:
    "Let agents read website and app performance from Google Analytics properties.",
  ConnectHelp: GoogleAnalyticsConnectHelp,
  icons: { google_analytics: GoogleAnalyticsLogo },
  providerKey: "google_analytics",
  toolRowPresenters: [],
} satisfies IntegrationUiModule
