// apps/web/src/integrations/airtable/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import {
  airtableGetRecordPresenter,
  airtableListRecordsPresenter,
} from "@/integrations/airtable/presenters/records"
import { AirtableLogo } from "@/integrations/airtable/components/logo"
import {
  airtableCreateRecordPresenter,
  airtableUpdateRecordPresenter,
} from "@/integrations/airtable/presenters/write"

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
