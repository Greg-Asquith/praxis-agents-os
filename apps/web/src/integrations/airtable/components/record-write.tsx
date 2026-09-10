// apps/web/src/integrations/airtable/components/record-write.tsx

import { CircleCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { microLabelClass } from "@/components/ui/stat"
import { AirtableFieldGrid } from "@/integrations/airtable/components/record-fields"
import type { AirtableWriteAction } from "@/integrations/airtable/lib/record-data"

export function AirtableFieldsToWrite({ fields }: { fields: Record<string, unknown> }) {
  return (
    <div className="grid min-w-0 gap-1">
      <p className={microLabelClass}>Fields to write</p>
      <AirtableFieldGrid fields={fields} />
    </div>
  )
}

export function AirtableWriteReceipt({
  action,
  recordId,
}: {
  action: AirtableWriteAction
  recordId: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="bg-success/10 text-success flex size-8 shrink-0 items-center justify-center rounded-full">
        <CircleCheckIcon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Record {action === "create" ? "created" : "updated"}</p>
        <code className="text-muted-foreground text-xs">{recordId}</code>
      </div>
      <Badge variant="success">Done</Badge>
    </div>
  )
}

export function AirtableWriteFailure({
  description,
  fields,
}: {
  description: string
  fields: Record<string, unknown> | null
}) {
  return (
    <div className="grid min-w-0 gap-3">
      <p className="text-destructive text-sm">{description}</p>
      {fields ? <AirtableFieldGrid fields={fields} /> : null}
    </div>
  )
}
