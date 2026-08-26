// apps/web/src/integrations/notion/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { NotionConnectHelp } from "@/integrations/notion/components/connect-help"
import { NotionLogo } from "@/integrations/notion/components/logo"

export default {
  catalogDescription: "Connect a Notion workspace and choose which pages agents can access.",
  ConnectHelp: NotionConnectHelp,
  icons: { notion: NotionLogo },
  providerKey: "notion",
} satisfies IntegrationUiModule
