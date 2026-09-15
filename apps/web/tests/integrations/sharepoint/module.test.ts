// apps/web/tests/integrations/sharepoint/module.test.ts

import { describe, expect, it } from "vitest"

import sharePointModule from "@/integrations/sharepoint"
import { testMicrosoftIntegrationModule } from "../microsoft-module-contract"

describe("SharePoint integration module", () => {
  it("registers the folder listing, search, and file read presenters", () => {
    expect(sharePointModule.toolRowPresenters.map((presenter) => presenter.key)).toEqual([
      "sharepoint_list_folder",
      "sharepoint_search_files",
      "sharepoint_read_file",
    ])
  })

  testMicrosoftIntegrationModule({
    description: "Let agents find and read files in SharePoint and OneDrive.",
    displayName: "SharePoint",
    module: sharePointModule,
    providerKey: "sharepoint",
    resourceType: "sharepoint_drive",
  })
})
