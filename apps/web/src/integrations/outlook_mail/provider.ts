// apps/web/src/integrations/outlook_mail/provider.ts

import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

// Mailbox identifiers are opaque Graph IDs, so cards show only the mailbox name.
export const outlookMailProvider: IntegrationProviderUi = {
  contextLabel: "Mailbox",
  externalLabel: null,
  fallbackDisplayName: "Selected mailbox",
  Logo: OutlookMailLogo,
  name: "Outlook",
  providerKey: "outlook_mail",
}
