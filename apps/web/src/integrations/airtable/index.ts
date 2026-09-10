// apps/web/src/integrations/airtable/index.ts

import { AirtableLogo } from "@/integrations/airtable/components/logo"
import {
  airtableGetRecordPresenter,
  airtableListRecordsPresenter,
} from "@/integrations/airtable/presenters/records"
import {
  airtableCreateRecordPresenter,
  airtableUpdateRecordPresenter,
} from "@/integrations/airtable/presenters/write"
import type { IntegrationUiModule } from "@/integrations/contract"

export default {
  catalogDescription: "Let agents read and update your Airtable records.",
  Logo: AirtableLogo,
  providerKey: "airtable",
  toolRowPresenters: [
    airtableListRecordsPresenter,
    airtableGetRecordPresenter,
    airtableCreateRecordPresenter,
    airtableUpdateRecordPresenter,
  ],
} satisfies IntegrationUiModule
