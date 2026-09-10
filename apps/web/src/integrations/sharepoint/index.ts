// apps/web/src/integrations/sharepoint/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { SharePointLogo } from "@/integrations/sharepoint/components/logo"

export default {
  catalogDescription: "Let agents find and read files in SharePoint and OneDrive.",
  ConnectHelp: MicrosoftConnectHelp,
  Logo: SharePointLogo,
  providerKey: "sharepoint",
} satisfies IntegrationUiModule
