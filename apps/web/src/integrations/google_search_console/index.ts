// apps/web/src/integrations/google_search_console/index.ts

import { GoogleSearchConsoleConnectHelp } from "@/integrations/google_search_console/components/connect-help"
import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"
import type { IntegrationUiModule } from "@/integrations/contract"

export default {
  catalogDescription:
    "Let agents read search performance and index status from Google Search Console properties.",
  ConnectHelp: GoogleSearchConsoleConnectHelp,
  icons: { google_search_console: GoogleSearchConsoleLogo },
  providerKey: "google_search_console",
  toolRowPresenters: [],
} satisfies IntegrationUiModule
