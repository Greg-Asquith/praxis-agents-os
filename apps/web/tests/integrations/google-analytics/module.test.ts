import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
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
    expect(integrationIcon("google_analytics")).toBe(googleAnalyticsModule.icons.google_analytics)
    expect(
      integrationToolRowPresenters("google_analytics").map((presenter) => presenter.key)
    ).toEqual([
      "google-analytics-run-report",
      "google-analytics-run-realtime-report",
      "google-analytics-list-report-fields",
      "google-analytics-check-report-fields",
      "google-analytics-list-google-ads-links",
    ])
    expect(googleAnalyticsModule.catalogDescription).toContain("website and app performance")
  })

  it("explains viewer access and both required APIs", () => {
    const html = renderToStaticMarkup(
      createElement(googleAnalyticsModule.ConnectHelp, {
        provider: {
          auth_modes: ["oauth", "service_account"],
          capability_flags: ["read"],
          configured: true,
          configured_auth_modes: { oauth: true, service_account: true },
          display_name: "Google Analytics",
          oauth_scopes: [],
          owner_scope: "workspace",
          provider_key: "google_analytics",
          required_form_fields: [],
          requires_discovery: true,
          resource_types: ["google_analytics_property"],
        },
      })
    )

    expect(html).toContain("Viewer")
    expect(html).toContain("Google Analytics Data API")
    expect(html).toContain("Admin API")
  })
})
