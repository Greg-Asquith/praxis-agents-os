// apps/web/src/integrations/airtable/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { AirtableWriteArgs } from "@/integrations/airtable/lib/record-data"
import { compactDetails, numberDetail, stringDetail } from "@/integrations/tool-details"

export function airtableRecordDetails(args: unknown): FanOutDetail[] {
  return compactDetails([
    stringDetail(args, "table", "Table"),
    stringDetail(args, "record_id", "Record"),
    stringDetail(args, "view", "View"),
    stringDetail(args, "filter_by_formula", "Filter", false),
    numberDetail(args, "max_records", "Maximum records"),
  ])
}

export function airtableWriteDetails(args: AirtableWriteArgs | null): FanOutDetail[] {
  if (!args) {
    return []
  }
  return [
    { label: "Table", value: args.table },
    ...(args.recordId === null ? [] : [{ label: "Record", value: args.recordId }]),
  ]
}
