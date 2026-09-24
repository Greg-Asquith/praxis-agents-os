import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import metaAdsModule from "@/integrations/meta_ads"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
} from "@/integrations/registry"

describe("Meta Ads integration module", () => {
  it("loads through the registry with its credential label and no presenters", async () => {
    await loadIntegrationUiModules(["meta_ads"])

    expect(integrationIcon("meta_ads")).toBe(metaAdsModule.Logo)
    expect(metaAdsModule.credentialLabel).toBe("Access token")
    expect(integrationToolRowPresenters("meta_ads")).toEqual([])
  })

  it("explains partner access, system user tasks, token permissions and revocation", () => {
    const html = renderToStaticMarkup(createElement(metaAdsModule.ConnectHelp))

    for (const text of [
      "partner",
      "Manage campaigns",
      "View performance",
      "Advertise",
      "Never",
      "ads_read",
      "ads_management",
      "business_management",
      "pages_show_list",
      "pages_manage_ads",
      "pages_read_engagement",
      "Look for New Resources",
      "personal user token",
      "revoke",
    ]) {
      expect(html).toContain(text)
    }
  })
})
