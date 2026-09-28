// apps/web/tests/integrations/google-search-console/module.test.ts

import { describe, expect, it } from "vitest"

import googleSearchConsoleModule from "@/integrations/google_search_console"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
} from "@/integrations/registry"

describe("Google Search Console integration module", () => {
  it("loads lazily through the registry with its icon and presenters", async () => {
    await loadIntegrationUiModules(["google_search_console"])

    expect(integrationIcon("google_search_console")).toBe(googleSearchConsoleModule.Logo)
    expect(integrationToolRowPresenters("google_search_console")).toHaveLength(5)
  })
})
