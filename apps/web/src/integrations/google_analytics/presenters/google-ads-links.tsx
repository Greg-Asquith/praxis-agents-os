// apps/web/src/integrations/google_analytics/presenters/google-ads-links.tsx

import { GoogleAnalyticsGoogleAdsLinksTable } from "@/integrations/google_analytics/components/google-ads-links-table"
import { parseGoogleAdsLinks } from "@/integrations/google_analytics/lib/google-ads-links-model"
import { googleAnalyticsProvider } from "@/integrations/google_analytics/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAnalyticsGoogleAdsLinksPresenter = defineIntegrationReadPresenter(
  googleAnalyticsProvider,
  {
    ariaLabel: "Linked Google Ads accounts",
    emptyLabel: "No Google Analytics properties were queried.",
    heading: "List Linked Google Ads Accounts",
    parseResult: parseGoogleAdsLinks,
    progressLabel: "Listing linked Google Ads accounts…",
    render: (links) => <GoogleAnalyticsGoogleAdsLinksTable links={links} />,
    tool: "google_analytics_list_google_ads_links",
  }
)
