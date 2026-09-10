// apps/web/src/integrations/google_search_console/presenters/sitemaps.tsx

import { SitemapsTable } from "@/integrations/google_search_console/components/sitemaps-table"
import { parseSitemapsData } from "@/integrations/google_search_console/lib/sitemaps-model"
import { googleSearchConsoleProvider } from "@/integrations/google_search_console/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleSearchConsoleSitemapsPresenter = defineIntegrationReadPresenter(
  googleSearchConsoleProvider,
  {
    ariaLabel: "Search Console sitemap results",
    emptyLabel: "No Search Console sites were queried.",
    heading: "List Search Console Sitemaps",
    parseResult: parseSitemapsData,
    progressLabel: "Listing Search Console sitemaps…",
    render: (rows, entry) => <SitemapsTable externalId={entry.externalId} rows={rows} />,
    tool: "google_search_console_list_sitemaps",
  }
)
