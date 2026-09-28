import { describe, expect, it } from "vitest"

import metaAdsModule from "@/integrations/meta_ads"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
} from "@/integrations/registry"

describe("Meta Ads integration module", () => {
  it("loads through the registry with its credential label and Insights presenter", async () => {
    await loadIntegrationUiModules(["meta_ads"])

    expect(integrationIcon("meta_ads")).toBe(metaAdsModule.Logo)
    expect(metaAdsModule.credentialLabel).toBe("Access token")
    expect(integrationToolRowPresenters("meta_ads").map((presenter) => presenter.key)).toEqual([
      "meta_ads_run_insights",
      "meta_ads_get_accounts",
      "meta_ads_list_objects",
      "meta_ads_list_custom_conversions",
      "meta_ads_list_activities",
    ])
  })
})
