// apps/web/src/integrations/airtable/presenters/records.tsx

import { AirtableRecordList } from "@/integrations/airtable/components/record-fields"
import {
  parseAirtableRecord,
  parseAirtableRecordList,
} from "@/integrations/airtable/lib/record-data"
import { airtableRecordDetails } from "@/integrations/airtable/lib/tool-details"
import { airtableProvider } from "@/integrations/airtable/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const airtableListRecordsPresenter = defineIntegrationReadPresenter(airtableProvider, {
  ariaLabel: "Airtable record results",
  details: airtableRecordDetails,
  emptyLabel: "No Airtable bases were queried.",
  heading: "List Airtable Records",
  parseResult: parseAirtableRecordList,
  progressLabel: "Loading Airtable records…",
  render: (result) => <AirtableRecordList records={result.records} />,
  tool: "airtable_list_records",
})

export const airtableGetRecordPresenter = defineIntegrationReadPresenter(airtableProvider, {
  ariaLabel: "Airtable record results",
  details: airtableRecordDetails,
  emptyLabel: "No Airtable bases returned this record.",
  heading: "Get Airtable Record",
  parseResult: parseAirtableRecord,
  progressLabel: "Loading Airtable record…",
  render: (record) => <AirtableRecordList records={[record]} />,
  tool: "airtable_get_record",
})
