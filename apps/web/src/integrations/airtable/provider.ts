// apps/web/src/integrations/airtable/provider.ts

import { AirtableLogo } from "@/integrations/airtable/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const airtableProvider: IntegrationProviderUi = {
  contextLabel: "Base",
  externalLabel: "Base ID",
  fallbackDisplayName: "Selected Airtable Base",
  Logo: AirtableLogo,
  name: "Airtable",
  providerKey: "airtable",
}
