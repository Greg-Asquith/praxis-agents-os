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
    expect(integrationIcon("notion")).toBe(notionModule.Logo)
    expect(integrationToolRowPresenters("notion").map((presenter) => presenter.key)).toEqual([
      "notion_search_pages",
      "notion_read_page",
      "notion_query_data_source",
      "notion-writes",
    ])
    expect(notionModule.catalogDescription).toContain("pages you choose")
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
          knowledge_source_supported: true,
          knowledge_source_resource_types: ["notion_workspace"],
        },
      })
    )

    expect(html).toContain("authorisation picker")
    expect(html).toContain("Other users authorise separately")
    expect(html).toContain("editor in this workspace")
  })
})
