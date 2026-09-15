// apps/web/src/integrations/sharepoint/provider.ts

import type { IntegrationProviderUi } from "@/integrations/provider-ui"
import { SharePointLogo } from "@/integrations/sharepoint/components/logo"

export const sharePointProvider: IntegrationProviderUi = {
  contextLabel: "Library",
  externalLabel: null,
  fallbackDisplayName: "Selected library",
  Logo: SharePointLogo,
  name: "SharePoint",
  providerKey: "sharepoint",
}
