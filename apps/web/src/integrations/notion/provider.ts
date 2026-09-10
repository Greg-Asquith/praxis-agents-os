// apps/web/src/integrations/notion/provider.ts

import { NotionLogo } from "@/integrations/notion/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const notionProvider: IntegrationProviderUi = {
  contextLabel: "Workspace",
  externalLabel: "Workspace ID",
  fallbackDisplayName: "Selected Notion workspace",
  Logo: NotionLogo,
  name: "Notion",
  providerKey: "notion",
}
