// apps/web/src/integrations/google_search_console/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { GoogleSearchConsoleConnectHelp } from "@/integrations/google_search_console/components/connect-help"
import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"
import { googleSearchConsoleInspectionPresenter } from "@/integrations/google_search_console/presenters/inspection"
import { googleSearchConsoleRequestIndexingPresenter } from "@/integrations/google_search_console/presenters/request-indexing"
import { googleSearchConsoleSearchAnalyticsPresenter } from "@/integrations/google_search_console/presenters/search-analytics"
import { googleSearchConsoleSitemapsPresenter } from "@/integrations/google_search_console/presenters/sitemaps"
import { googleSearchConsoleSubmitSitemapPresenter } from "@/integrations/google_search_console/presenters/submit-sitemap"

export default {
  catalogDescription:
    "Let agents read search performance and index status, submit sitemaps, and send approval-only Indexing API notifications for eligible pages.",
  ConnectHelp: GoogleSearchConsoleConnectHelp,
  Logo: GoogleSearchConsoleLogo,
  providerKey: "google_search_console",
  toolRowPresenters: [
    googleSearchConsoleSearchAnalyticsPresenter,
    googleSearchConsoleSitemapsPresenter,
    googleSearchConsoleInspectionPresenter,
    googleSearchConsoleSubmitSitemapPresenter,
    googleSearchConsoleRequestIndexingPresenter,
  ],
} satisfies IntegrationUiModule
