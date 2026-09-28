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
  })
})
