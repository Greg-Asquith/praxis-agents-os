// apps/web/tests/integrations/outlook_calendar/module.test.ts

import { describe } from "vitest"

import outlookCalendarModule from "@/integrations/outlook_calendar"
import { testMicrosoftIntegrationModule } from "../microsoft-module-contract"

describe("Outlook Calendar integration module", () => {
  testMicrosoftIntegrationModule({
    description: "Let agents read and manage your Outlook calendar.",
    displayName: "Outlook Calendar",
    module: outlookCalendarModule,
    providerKey: "outlook_calendar",
    resourceType: "outlook_calendar",
  })
})
