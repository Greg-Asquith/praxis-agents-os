import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import notionModule from "@/integrations/notion"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
  providerKeyForToolName,
} from "@/integrations/registry"

describe("Notion integration module", () => {
  it("loads lazily through the registry with its icon", async () => {
    await loadIntegrationUiModules(["notion"])

    expect(providerKeyForToolName("notion_search_pages")).toBe("notion")
    expect(integrationIcon("notion")).toBe(notionModule.icons.notion)
    expect(integrationToolRowPresenters("notion")).toEqual([])
    expect(notionModule.catalogDescription).toContain("choose which pages")
  })

  it("explains page selection and personal authorization", () => {
    const html = renderToStaticMarkup(
      createElement(notionModule.ConnectHelp, {
        provider: {
          auth_modes: ["oauth"],
          capability_flags: ["read", "write"],
          configured: true,
          configured_auth_modes: { oauth: true },
          display_name: "Notion",
          oauth_scopes: [],
          owner_scope: "user",
          provider_key: "notion",
          required_form_fields: [],
          requires_discovery: true,
          resource_types: ["notion_workspace"],
          table_scopes_supported: false,
        },
      })
    )

    expect(html).toContain("authorization picker")
    expect(html).toContain("Other Praxis users authorize separately")
    expect(html).toContain("editor in this Praxis workspace")
  })
})
