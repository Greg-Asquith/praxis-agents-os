// apps/web/src/integrations/gmail/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { GmailLogo } from "@/integrations/gmail/logo"

export default {
  catalogDescription: "Let agents read and manage your emails.",
  icons: { gmail: GmailLogo },
  providerKey: "gmail",
} satisfies IntegrationUiModule
