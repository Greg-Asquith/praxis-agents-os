// apps/web/src/integrations/google_search_console/index.ts

import { GoogleSearchConsoleConnectHelp } from "@/integrations/google_search_console/components/connect-help"
import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"
import { inspectionPresenter } from "@/integrations/google_search_console/presenters/inspection"
import { requestIndexingPresenter } from "@/integrations/google_search_console/presenters/request-indexing"
import { searchAnalyticsPresenter } from "@/integrations/google_search_console/presenters/search-analytics"
import { sitemapsPresenter } from "@/integrations/google_search_console/presenters/sitemaps"
import { submitSitemapPresenter } from "@/integrations/google_search_console/presenters/submit-sitemap"
import type { IntegrationUiModule } from "@/integrations/contract"

export default {
  catalogDescription:
    "Let agents read search performance and index status, submit sitemaps, and send approval-only Indexing API notifications for eligible pages.",
  ConnectHelp: GoogleSearchConsoleConnectHelp,
  icons: { google_search_console: GoogleSearchConsoleLogo },
  providerKey: "google_search_console",
  toolRowPresenters: [
    searchAnalyticsPresenter,
    sitemapsPresenter,
    inspectionPresenter,
    submitSitemapPresenter,
    requestIndexingPresenter,
  ],
} satisfies IntegrationUiModule
