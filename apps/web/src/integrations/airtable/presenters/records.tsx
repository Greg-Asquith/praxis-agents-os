// apps/web/src/integrations/airtable/records-presenter.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { parseAirtableRecord, type AirtableRecord } from "@/integrations/airtable/record-data"
import { AirtableRecordList } from "@/integrations/airtable/record-fields"
import { airtableRecordDetails } from "@/integrations/airtable/tool-details"
import { AirtableToolHeading } from "@/integrations/airtable/tool-heading"
import { isRecord } from "@/lib/guards"

type AirtableRecordListResult = {
  records: AirtableRecord[]
  total: number
}

export const airtableListRecordsPresenter: ToolRowPresenter = {
  key: "airtable-list-records",
  matches: (activity) => activity.name === "airtable_list_records",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<AirtableToolHeading>List Airtable Records</AirtableToolHeading>}
          label="Loading Airtable records…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, recordListResult)
    if (!fanOut) {
      return null
    }
    return (
      <div aria-label="Airtable record results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Base"
          defaultOpen={defaultOpen}
          details={airtableRecordDetails(activity.args)}
          entries={fanOut.entries}
          emptyLabel="No Airtable bases were queried."
          externalLabel="Base ID"
          heading={<AirtableToolHeading>List Airtable Records</AirtableToolHeading>}
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            return result ? <AirtableRecordList records={result.records} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

export const airtableGetRecordPresenter: ToolRowPresenter = {
  key: "airtable-get-record",
  matches: (activity) => activity.name === "airtable_get_record",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<AirtableToolHeading>Get Airtable Record</AirtableToolHeading>}
          label="Loading Airtable record…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseAirtableRecord)
    if (!fanOut) {
      return null
    }
    return (
      <div aria-label="Airtable record results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Base"
          defaultOpen={defaultOpen}
          details={airtableRecordDetails(activity.args)}
          entries={fanOut.entries}
          emptyLabel="No Airtable bases returned this record."
          externalLabel="Base ID"
          heading={<AirtableToolHeading>Get Airtable Record</AirtableToolHeading>}
        >
          {(_entry, index) => {
            const record = fanOut.data[index]
            return record ? <AirtableRecordList records={[record]} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function recordListResult(value: unknown): AirtableRecordListResult | null {
  if (!isRecord(value) || !Array.isArray(value["records"]) || typeof value["total"] !== "number") {
    return null
  }
  const records: AirtableRecord[] = []
  for (const item of value["records"]) {
    const record = parseAirtableRecord(item)
    if (!record) {
      return null
    }
    records.push(record)
  }
  return { records, total: value["total"] }
}
