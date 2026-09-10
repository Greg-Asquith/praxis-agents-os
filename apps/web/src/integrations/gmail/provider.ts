// apps/web/src/integrations/gmail/provider.ts

import { GmailLogo } from "@/integrations/gmail/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const gmailProvider: IntegrationProviderUi = {
  contextLabel: "Mailbox",
  externalLabel: "Email",
  fallbackDisplayName: "Selected Mailbox",
  Logo: GmailLogo,
  name: "Gmail",
  providerKey: "gmail",
}
