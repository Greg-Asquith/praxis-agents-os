// apps/web/src/integrations/airtable/components/write-outcome.tsx

import { CircleCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { AirtableFieldGrid } from "@/integrations/airtable/components/record-fields"

export function AirtableWriteReceipt({
  action,
  recordId,
}: {
  action: "create" | "update"
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
      {fields ? (
        <div className="border-border/70 overflow-hidden rounded-lg border">
          <AirtableFieldGrid fields={fields} />
        </div>
      ) : null}
    </div>
  )
}
