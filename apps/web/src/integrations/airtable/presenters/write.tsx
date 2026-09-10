// apps/web/src/integrations/airtable/presenters/write.tsx

import {
  AirtableFieldsToWrite,
  AirtableWriteFailure,
  AirtableWriteReceipt,
} from "@/integrations/airtable/components/record-write"
import {
  parseAirtableRecordId,
  parseAirtableWriteArgs,
  type AirtableWriteAction,
  type AirtableWriteArgs,
} from "@/integrations/airtable/lib/record-data"
import { airtableWriteDetails } from "@/integrations/airtable/lib/tool-details"
import { airtableProvider } from "@/integrations/airtable/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const airtableCreateRecordPresenter = createIntegrationWritePresenter({
  variants: { airtable_create_record: recordWrite("create") },
})

export const airtableUpdateRecordPresenter = createIntegrationWritePresenter({
  variants: { airtable_update_record: recordWrite("update") },
})

function recordWrite(action: AirtableWriteAction) {
  const parseArgs = (value: unknown) => parseAirtableWriteArgs(value, action)
  return defineIntegrationWriteVariant<AirtableWriteArgs, string>(airtableProvider, {
    approval: {
      parseArgs,
      prompt: `The agent wants to ${action} this record in the selected Airtable bases.`,
      renderSummary: (value, fallback) => (
        <AirtableFieldsToWrite fields={(parseArgs(value) ?? fallback).fields} />
      ),
    },
    copy:
      action === "create"
        ? { effect: "created", object: "record", verb: "Create" }
        : { effect: "updated", object: "record", verb: "Update" },
    details: airtableWriteDetails,
    parseResult: parseAirtableRecordId,
    renderFailure: (args, description) => (
      <AirtableWriteFailure description={description} fields={args?.fields ?? null} />
    ),
    renderOutcome: (recordId) => <AirtableWriteReceipt action={action} recordId={recordId} />,
  })
}
