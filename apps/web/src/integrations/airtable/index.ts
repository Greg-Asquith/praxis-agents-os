// apps/web/src/integrations/airtable/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import {
  airtableGetRecordPresenter,
  airtableListRecordsPresenter,
} from "@/integrations/airtable/records-presenter"
import { AirtableLogo } from "@/integrations/airtable/logo"
import {
  airtableCreateRecordPresenter,
  airtableUpdateRecordPresenter,
} from "@/integrations/airtable/write-presenter"

export default {
  catalogDescription: "Let agents work with your Airtable records.",
  icons: { airtable: AirtableLogo },
  providerKey: "airtable",
  toolRowPresenters: [
    airtableListRecordsPresenter,
    airtableGetRecordPresenter,
    airtableCreateRecordPresenter,
    airtableUpdateRecordPresenter,
  ],
} satisfies IntegrationUiModule
