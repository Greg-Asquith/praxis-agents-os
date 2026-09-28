import { describe, expect, it } from "vitest"

import googleAnalyticsModule from "@/integrations/google_analytics"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
  providerKeyForToolName,
} from "@/integrations/registry"

describe("Google Analytics integration module", () => {
  it("loads lazily through the registry with its icon and presenters", async () => {
    await loadIntegrationUiModules(["google_analytics"])

    expect(providerKeyForToolName("google_analytics_run_report")).toBe("google_analytics")
    expect(integrationIcon("google_analytics")).toBe(googleAnalyticsModule.Logo)
    expect(
      integrationToolRowPresenters("google_analytics").map((presenter) => presenter.key)
    ).toEqual([
      "google_analytics_run_report",
      "google_analytics_run_realtime_report",
      "google_analytics_list_report_fields",
      "google_analytics_check_report_fields",
      "google_analytics_list_google_ads_links",
    ])
  })
})
