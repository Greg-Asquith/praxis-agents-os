// apps/web/tests/integrations/sharepoint/module.test.ts

import { describe } from "vitest"

import sharePointModule from "@/integrations/sharepoint"
import { testMicrosoftIntegrationModule } from "../microsoft-module-contract"

describe("SharePoint integration module", () => {
  testMicrosoftIntegrationModule({
    description: "Let agents find, read, and save files in SharePoint and OneDrive.",
    displayName: "SharePoint",
    module: sharePointModule,
    providerKey: "sharepoint",
    resourceType: "sharepoint_drive",
  })
})
