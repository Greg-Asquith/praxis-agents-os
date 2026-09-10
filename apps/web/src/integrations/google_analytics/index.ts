// apps/web/src/integrations/google_analytics/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { GoogleAnalyticsConnectHelp } from "@/integrations/google_analytics/components/connect-help"
import { GoogleAnalyticsLogo } from "@/integrations/google_analytics/components/logo"
import { googleAnalyticsCompatibilityPresenter } from "@/integrations/google_analytics/presenters/compatibility"
import { googleAnalyticsGoogleAdsLinksPresenter } from "@/integrations/google_analytics/presenters/google-ads-links"
import { googleAnalyticsRealtimePresenter } from "@/integrations/google_analytics/presenters/realtime"
import { googleAnalyticsReportPresenter } from "@/integrations/google_analytics/presenters/report"
import { googleAnalyticsReportFieldsPresenter } from "@/integrations/google_analytics/presenters/report-fields"

export default {
  catalogDescription:
    "Let agents read website and app performance from Google Analytics properties.",
  ConnectHelp: GoogleAnalyticsConnectHelp,
  Logo: GoogleAnalyticsLogo,
  providerKey: "google_analytics",
  toolRowPresenters: [
    googleAnalyticsReportPresenter,
    googleAnalyticsRealtimePresenter,
    googleAnalyticsReportFieldsPresenter,
    googleAnalyticsCompatibilityPresenter,
    googleAnalyticsGoogleAdsLinksPresenter,
  ],
} satisfies IntegrationUiModule
