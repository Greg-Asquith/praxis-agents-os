// apps/web/src/integrations/outlook_mail/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"

export default {
  catalogDescription: "Let agents read and manage your Outlook email.",
  ConnectHelp: MicrosoftConnectHelp,
  icons: { outlook_mail: OutlookMailLogo },
  providerKey: "outlook_mail",
} satisfies IntegrationUiModule
