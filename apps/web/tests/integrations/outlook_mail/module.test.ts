// apps/web/tests/integrations/outlook_mail/module.test.ts

import { describe } from "vitest"

import outlookMailModule from "@/integrations/outlook_mail"
import { testMicrosoftIntegrationModule } from "../microsoft-module-contract"

describe("Outlook Mail integration module", () => {
  testMicrosoftIntegrationModule({
    description: "Let agents read and manage your Outlook email.",
    displayName: "Outlook Mail",
    module: outlookMailModule,
    providerKey: "outlook_mail",
    resourceType: "outlook_mailbox",
  })
})
