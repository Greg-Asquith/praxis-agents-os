// apps/web/src/integrations/airtable/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { AirtableLogo } from "@/integrations/airtable/logo"

export default {
  catalogDescription: "Let agents work with your Airtable records.",
  icons: { airtable: AirtableLogo },
  providerKey: "airtable",
} satisfies IntegrationUiModule
