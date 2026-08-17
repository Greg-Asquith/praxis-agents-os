// apps/web/src/integrations/google_analytics/index.ts

import { GoogleAnalyticsConnectHelp } from "@/integrations/google_analytics/components/connect-help"
import { GoogleAnalyticsLogo } from "@/integrations/google_analytics/components/logo"
import { compatibilityPresenter } from "@/integrations/google_analytics/presenters/compatibility"
import { realtimePresenter } from "@/integrations/google_analytics/presenters/realtime"
import { reportFieldsPresenter } from "@/integrations/google_analytics/presenters/report-fields"
import { reportPresenter } from "@/integrations/google_analytics/presenters/report"
import type { IntegrationUiModule } from "@/integrations/contract"

export default {
  catalogDescription:
    "Let agents read website and app performance from Google Analytics properties.",
  ConnectHelp: GoogleAnalyticsConnectHelp,
  icons: { google_analytics: GoogleAnalyticsLogo },
  providerKey: "google_analytics",
  toolRowPresenters: [
    reportPresenter,
    realtimePresenter,
    reportFieldsPresenter,
    compatibilityPresenter,
  ],
} satisfies IntegrationUiModule
