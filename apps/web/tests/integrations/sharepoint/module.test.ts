// apps/web/tests/integrations/sharepoint/module.test.ts

import { describe, expect, it } from "vitest"

import sharePointModule from "@/integrations/sharepoint"
import { testMicrosoftIntegrationModule } from "../microsoft-module-contract"

describe("SharePoint integration module", () => {
  it("registers all nine SharePoint read and write presenters", () => {
    expect(sharePointModule.toolRowPresenters.map((presenter) => presenter.key)).toEqual([
      "sharepoint_list_folder",
      "sharepoint_search_files",
      "sharepoint_read_file",
      "sharepoint_open_link",
      "sharepoint_find_in_file",
      "sharepoint_create_folder",
      "sharepoint_write_file",
      "sharepoint_update_file",
      "sharepoint_copy_to_files",
    ])
  })

  testMicrosoftIntegrationModule({
    description: "Let agents find, read, and save files in SharePoint and OneDrive.",
    displayName: "SharePoint",
    module: sharePointModule,
    providerKey: "sharepoint",
    resourceType: "sharepoint_drive",
  })
})
