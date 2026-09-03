import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import googleSearchConsoleModule from "@/integrations/google_search_console"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
} from "@/integrations/registry"

describe("Google Search Console integration module", () => {
  it("loads lazily through the registry with its icon and no presenters", async () => {
    await loadIntegrationUiModules(["google_search_console"])

    expect(integrationIcon("google_search_console")).toBe(
      googleSearchConsoleModule.icons.google_search_console
    )
    expect(integrationToolRowPresenters("google_search_console")).toEqual([])
    expect(googleSearchConsoleModule.catalogDescription).toContain("search performance")
  })

  it("explains property access and API enablement", () => {
    const html = renderToStaticMarkup(
      createElement(googleSearchConsoleModule.ConnectHelp, {
        provider: {
          auth_modes: ["oauth"],
          capability_flags: ["read", "write"],
          configured: true,
          configured_auth_modes: { oauth: true },
          display_name: "Google Search Console",
          oauth_scopes: [],
          owner_scope: "workspace",
          provider_key: "google_search_console",
          required_form_fields: [],
          requires_discovery: true,
          resource_types: ["google_search_console_site"],
          table_scopes_supported: false,
          knowledge_source_supported: false,
          knowledge_source_resource_types: [],
        },
      })
    )

    expect(html).toContain("Owner permission")
    expect(html).toContain("sitemap submissions")
    expect(html).toContain("Google Search Console API")
    expect(html).not.toContain("service account")
  })
})
