// apps/web/src/integrations/outlook_calendar/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { OutlookCalendarLogo } from "@/integrations/outlook_calendar/components/logo"

export default {
  catalogDescription: "Let agents read and manage your Outlook calendar.",
  ConnectHelp: MicrosoftConnectHelp,
  Logo: OutlookCalendarLogo,
  providerKey: "outlook_calendar",
} satisfies IntegrationUiModule
