// apps/web/src/integrations/airtable/components/record-fields.tsx

import { CalendarClockIcon } from "lucide-react"

import { ExternalContent } from "@/components/tool-ui/external-content"
import { resolveToolField, type ToolFieldFormat } from "@/components/tool-ui/field-resolution"
import { fieldLabelClass, readOnlyFieldWellClass } from "@/components/tool-ui/field-styles"
import { ToolFieldValue } from "@/components/tool-ui/field-value"
import { isUntrustedNode, nodeText } from "@/components/tool-ui/untrusted-node"
import { Badge } from "@/components/ui/badge"
import type { AirtableRecord } from "@/integrations/airtable/lib/record-data"
import { formatDateTime } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

const LONG_TEXT_LENGTH = 160

export function AirtableRecordList({ records }: { records: AirtableRecord[] }) {
  if (records.length === 0) {
    return (
      <p className="text-muted-foreground py-4 text-center text-sm">
        No Airtable records were found.
      </p>
    )
  }
  return (
    <div className="grid min-w-0 gap-3" role="list">
      {records.map((record) => (
        <article
          aria-label={`Airtable record ${record.recordId}`}
          className="border-border min-w-0 overflow-hidden rounded-lg border"
          key={record.recordId}
          role="listitem"
        >
          <header className="flex min-w-0 flex-wrap items-center gap-2 border-b px-3 py-2">
            <code className="min-w-0 flex-1 truncate text-xs">{record.recordId}</code>
            {record.createdTime ? (
              <Badge variant="outline">
                <CalendarClockIcon />
                {formatDateTime(record.createdTime)}
              </Badge>
            ) : null}
          </header>
          <AirtableFieldGrid fields={record.fields} />
        </article>
      ))}
    </div>
  )
}

export function AirtableFieldGrid({ fields }: { fields: Record<string, unknown> }) {
  const entries = Object.entries(fields)
  if (entries.length === 0) {
    return <p className="text-muted-foreground p-3 text-sm">No field values were returned.</p>
  }
  return (
    <dl className="divide-border grid min-w-0 divide-y">
      {entries.map(([label, value]) => (
        <div
          className="grid min-w-0 gap-1.5 px-3 py-2.5 sm:grid-cols-[minmax(8rem,0.35fr)_minmax(0,1fr)] sm:gap-4"
          key={label}
        >
          <dt className={cn(fieldLabelClass, "pt-1")}>{label}</dt>
          <dd className="min-w-0">
            <AirtableFieldValue label={label} value={value} />
          </dd>
        </div>
      ))}
    </dl>
  )
}

function AirtableFieldValue({ label, value }: { label: string; value: unknown }) {
  if (value === null) {
    return <span className="text-muted-foreground text-sm">Empty</span>
  }
  if (isUntrustedNode(value)) {
    return <ExternalContent label={`${label} external content`} value={value} />
  }
  if (typeof value === "string" && value.length > LONG_TEXT_LENGTH) {
    return <ExternalContent label={label} showSource={false} value={value} />
  }

  const format = fieldFormat(value)
  const field = format ? resolveToolField({ format, key: label, label }, value) : null
  if (field) {
    return (
      <div className={cn(readOnlyFieldWellClass, "wrap-break-word")}>
        <ToolFieldValue field={field} />
      </div>
    )
  }

  return (
    <ExternalContent
      label={label}
      showSource={containsUntrustedNode(value)}
      value={airtableJsonText(value)}
    />
  )
}

function fieldFormat(value: unknown): ToolFieldFormat | null {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return "text"
  }
  if (
    Array.isArray(value) &&
    value.every(
      (item) => nodeText(item) !== null || typeof item === "number" || typeof item === "string"
    )
  ) {
    return "list"
  }
  return null
}

function containsUntrustedNode(value: unknown): boolean {
  if (isUntrustedNode(value)) {
    return true
  }
  if (Array.isArray(value)) {
    return value.some(containsUntrustedNode)
  }
  return isRecord(value) && Object.values(value).some(containsUntrustedNode)
}

function airtableJsonText(value: unknown): string {
  return JSON.stringify(replaceNodes(value), null, 2)
}

function replaceNodes(value: unknown): unknown {
  const text = nodeText(value)
  if (text !== null) {
    return text
  }
  if (Array.isArray(value)) {
    return value.map(replaceNodes)
  }
  if (isRecord(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, replaceNodes(item)]))
  }
  return value
}
