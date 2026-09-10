// apps/web/src/integrations/google_search_console/provider.ts

import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const googleSearchConsoleProvider: IntegrationProviderUi = {
  contextLabel: "Site",
  externalLabel: "Site URL",
  fallbackDisplayName: "Selected Search Console site",
  Logo: GoogleSearchConsoleLogo,
  name: "Search Console",
  providerKey: "google_search_console",
}
