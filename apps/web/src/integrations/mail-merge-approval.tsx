// apps/web/src/integrations/mail-merge-approval.tsx

import { PencilIcon, SendIcon } from "lucide-react"
import { useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedRecords, EditedValue } from "@/components/tool-ui/edited-values"
import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { HtmlFieldInput } from "@/components/tool-ui/html-field-input"
import { KeyValueFieldInput } from "@/components/tool-ui/keyvalue-field-input"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { ChangeSummary } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import {
  countOf,
  extraColumns,
  fillMergeTemplate,
  finishText,
  readyCount,
  recipientValues,
  STANDARD_COLUMNS,
  type MailMergeArgs,
  type MergeRecipient,
  type RowCheck,
} from "@/integrations/mail-merge"
import { formatTime } from "@/lib/format"

const PAGE_SIZE = 25
const SKIP_TEXT = {
  do_not_email: "On the Do Not Email list",
  duplicate: "Already in the list",
  sender: "Your own address",
} as const
const COLUMNS: DataColumn[] = [
  { key: "email", kind: "text", label: "Email" },
  { key: "name", kind: "text", label: "Name" },
  { key: "other", kind: "text", label: "Other Columns" },
  { key: "status", kind: "text", label: "Status" },
  { key: "edit", kind: "text", label: "" },
]
const TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  { id: "ready", label: "Ready", match: (row) => row["state"] === "ready" },
  {
    id: "needs_attention",
    label: "Needs Attention",
    match: (row) => row["state"] === "needs_attention",
    hideWhenEmpty: true,
  },
  {
    id: "skipped",
    label: "Skipped",
    match: (row) => row["state"] === "skipped",
    hideWhenEmpty: true,
  },
  {
    id: "unchecked",
    label: "Changed",
    match: (row) => row["state"] === "unchecked",
    hideWhenEmpty: true,
  },
]

export function MailMergeApprovalSummary({
  args,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: MailMergeArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState<string | undefined>(undefined)
  const [selected, setSelected] = useState<number | null>(null)
  const counts = statusCounts(args)
  const firstReady = args.checks.findIndex((check) => check?.status === "ready")
  const previewIndex = selected ?? (firstReady >= 0 ? firstReady : 0)
  const extras = extraColumns(args)
  const editRecipients = (next: MergeRecipient[]) => {
    onFieldEdit("recipients", next.map(rawRecipient))
  }
  const needsAttention = args.recipients.filter(
    (_recipient, index) => args.checks[index]?.status === "needs_attention"
  )
  return (
    <div className="grid min-w-0 gap-4">
      <ChangeSummary
        lines={[
          { id: "ready", label: "Ready", count: counts.ready },
          {
            id: "needs_attention",
            label: "Needs Attention",
            detail: "Not sent until fixed",
            count: counts.needs_attention,
            tone: "warning",
            selected: tab === "needs_attention",
            onSelect: () => {
              setTab("needs_attention")
            },
          },
          {
            id: "skipped",
            label: "Skipped",
            detail: "Do Not Email, repeated, or your own address",
            count: counts.skipped,
            selected: tab === "skipped",
            onSelect: () => {
              setTab("skipped")
            },
          },
          {
            id: "unchecked",
            label: "Changed",
            detail: "Checked again when you send a test or approve",
            count: counts.unchecked,
          },
        ]}
      />
      <PaceLine args={args} />
      <div className="grid gap-1.5">
        <Label htmlFor="mail-merge-subject">Subject</Label>
        <Input
          disabled={disabled}
          id="mail-merge-subject"
          onChange={(event) => {
            onFieldEdit("subject", event.currentTarget.value)
          }}
          value={args.subject}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="mail-merge-body">Message</Label>
        <HtmlFieldInput
          disabled={disabled}
          id="mail-merge-body"
          label="Message"
          onChange={(value) => {
            onFieldEdit("body_html", value)
          }}
          value={args.bodyHtml}
        />
        <Placeholders columns={[...STANDARD_COLUMNS, ...extras]} />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="mail-merge-fallbacks">Fallbacks</Label>
        <p className="text-muted-foreground text-xs">
          Text used when a recipient has no value, such as &quot;there&quot; for first_name.
        </p>
        <KeyValueFieldInput
          ariaLabel="Fallbacks"
          disabled={disabled}
          id="mail-merge-fallbacks"
          lockedEntries={[]}
          onChange={(value) => {
            onFieldEdit(
              "fallbacks",
              Object.fromEntries(Object.entries(value).map(([key, item]) => [key, String(item)]))
            )
          }}
          value={args.fallbacks}
        />
      </div>
      <DataTable
        activeTab={tab ?? "all"}
        columns={extras.length > 0 ? COLUMNS : COLUMNS.filter((column) => column.key !== "other")}
        onRowClick={(row) => {
          if (typeof row["index"] === "number") setSelected(row["index"])
        }}
        onTabChange={setTab}
        pageSize={PAGE_SIZE}
        renderCell={(column, row) => {
          const index = typeof row["index"] === "number" ? row["index"] : -1
          const recipient = args.recipients[index]
          if (!recipient) return null
          if (column.key === "status") return <StatusCell check={args.checks[index] ?? null} />
          if (column.key === "edit")
            return (
              <RecipientEditor
                disabled={disabled}
                extraColumns={extras}
                onChange={(next) => {
                  editRecipients(args.recipients.map((item, at) => (at === index ? next : item)))
                }}
                onRemove={() => {
                  editRecipients(args.recipients.filter((_item, at) => at !== index))
                }}
                recipient={recipient}
              />
            )
          return null
        }}
        rowClassName={(row) => (row["index"] === previewIndex ? "bg-accent/50" : undefined)}
        rowDetails={false}
        rowNoun={["recipient", "recipients"]}
        rows={args.recipients.map((recipient, index) => ({
          index,
          email: recipient.email,
          name: [recipient.firstName, recipient.lastName].filter(Boolean).join(" "),
          other: Object.entries(recipient.fields)
            .map(([key, value]) => `${key}: ${value}`)
            .join(", "),
          status: statusText(args.checks[index] ?? null),
          state: args.checks[index]?.status ?? "unchecked",
        }))}
        searchable={args.recipients.length > PAGE_SIZE}
        tabs={TABS}
        summary={
          tab === "needs_attention" && needsAttention.length > 0 ? (
            <Button
              disabled={disabled}
              onClick={() => {
                editRecipients(
                  args.recipients.filter(
                    (_recipient, index) => args.checks[index]?.status !== "needs_attention"
                  )
                )
                setTab(undefined)
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              Cancel These {needsAttention.length}
            </Button>
          ) : null
        }
      />
      <MergePreview args={args} index={previewIndex} />
      <TestSend args={args} controls={controls} disabled={disabled} />
    </div>
  )
}

function PaceLine({ args }: { args: MailMergeArgs }) {
  if (!args.budget) return null
  const ready = readyCount(args)
  const waiting = Math.max(0, ready - args.budget.remaining)
  return (
    <p className="text-muted-foreground text-sm">
      This mailbox can send {countOf(args.budget.remaining, "more mail merge email")} in the next 24
      hours.
      {waiting > 0
        ? ` The other ${countOf(waiting, "email")} will wait for room and go out later.`
        : ""}
      {args.estimatedFinish
        ? ` Expected to finish around ${finishText(args.estimatedFinish)}.`
        : ""}
    </p>
  )
}

function Placeholders({ columns }: { columns: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-muted-foreground text-xs">Placeholders:</span>
      {columns.map((column) => (
        <Badge key={column} className="font-mono" variant="outline">
          {`{{${column}}}`}
        </Badge>
      ))}
    </div>
  )
}

function MergePreview({ args, index }: { args: MailMergeArgs; index: number }) {
  const recipient = args.recipients[index]
  if (!recipient) return null
  const values = recipientValues(recipient)
  const subject = fillMergeTemplate(args.subject, values, args.fallbacks, false)
  const body = fillMergeTemplate(args.bodyHtml, values, args.fallbacks, true)
  const missing = [...new Set([...subject.missing, ...body.missing])]
  return (
    <section aria-label="Email preview" className="grid gap-2 rounded-lg border p-3">
      <div className="grid gap-0.5 text-sm">
        <span>
          <span className="text-muted-foreground">To: </span>
          {recipient.email}
        </span>
        <span>
          <span className="text-muted-foreground">Subject: </span>
          {subject.text}
        </span>
      </div>
      {missing.length > 0 ? (
        <p className="text-warning-text text-sm">
          No value or fallback for {missing.join(", ")}, so this email won&apos;t be sent.
        </p>
      ) : null}
      <HtmlContentFrame className="h-64 rounded-md border" html={body.text} title="Email preview" />
      <p className="text-muted-foreground text-xs">Select a recipient to preview their email.</p>
    </section>
  )
}

function TestSend({
  args,
  controls,
  disabled,
}: {
  args: MailMergeArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
}) {
  const sender = args.sender ?? "your own address"
  const note = controls.submitting
    ? "Sending your test…"
    : !args.needsTest && args.test
      ? `Test sent to ${args.test.sentTo} at ${formatTime(args.test.sentAt)}, using ${args.test.recipient}'s details. Check it, then approve.`
      : `Send yourself a test first. It goes only to ${sender}, using the first ready recipient's details.`
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-muted-foreground text-sm" role="status">
        {note}
      </p>
      <Button
        disabled={
          disabled ||
          !controls.onReview ||
          Boolean(args.templateProblem) ||
          args.needsReconnect ||
          readyCount(args) === 0
        }
        onClick={controls.onReview}
        type="button"
        variant={args.needsTest ? "default" : "outline"}
      >
        <SendIcon aria-hidden="true" />
        {args.needsTest ? "Send Me a Test" : "Send Another Test"}
      </Button>
    </div>
  )
}

function RecipientEditor({
  disabled,
  extraColumns,
  onChange,
  onRemove,
  recipient,
}: {
  disabled: boolean
  extraColumns: string[]
  onChange: (recipient: MergeRecipient) => void
  onRemove: () => void
  recipient: MergeRecipient
}) {
  const fields: ["email" | "firstName" | "lastName", string][] = [
    ["email", "Email"],
    ["firstName", "First Name"],
    ["lastName", "Last Name"],
  ]
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            aria-label={`Edit ${recipient.email}`}
            disabled={disabled}
            onClick={(event) => {
              event.stopPropagation()
            }}
            size="icon-sm"
            type="button"
            variant="ghost"
          />
        }
      >
        <PencilIcon className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[70vh] w-[min(22rem,calc(100vw-2rem))] gap-3 overflow-y-auto"
      >
        <PopoverHeader>
          <PopoverTitle>Recipient</PopoverTitle>
        </PopoverHeader>
        {fields.map(([key, label]) => (
          <div key={key} className="grid gap-1">
            <Label className="text-xs">{label}</Label>
            <CommittedInput
              ariaLabel={label}
              disabled={disabled}
              onCommit={(value) => {
                onChange({ ...recipient, [key]: value })
              }}
              value={recipient[key]}
            />
          </div>
        ))}
        {extraColumns.map((column) => (
          <div key={column} className="grid gap-1">
            <Label className="font-mono text-xs">{column}</Label>
            <CommittedInput
              ariaLabel={column}
              disabled={disabled}
              onCommit={(value) => {
                onChange({ ...recipient, fields: withField(recipient.fields, column, value) })
              }}
              value={recipient.fields[column] ?? ""}
            />
          </div>
        ))}
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={onRemove}
          size="sm"
          type="button"
          variant="outline"
        >
          Remove Recipient
        </Button>
      </PopoverContent>
    </Popover>
  )
}

function StatusCell({ check }: { check: RowCheck | null }) {
  if (!check) return <span className="text-muted-foreground text-sm">Checked at the next test</span>
  const detail =
    check.status === "skipped"
      ? check.skipReason
        ? SKIP_TEXT[check.skipReason]
        : null
      : [...check.problems, ...check.warnings].join(" ") || null
  return (
    <span className="grid min-w-0 gap-0.5 whitespace-normal">
      <Badge
        className="w-fit"
        variant={
          check.status === "ready"
            ? "success"
            : check.status === "needs_attention"
              ? "warning"
              : "secondary"
        }
      >
        {statusText(check)}
      </Badge>
      {detail ? <span className="text-muted-foreground text-xs">{detail}</span> : null}
    </span>
  )
}

function statusCounts(args: MailMergeArgs) {
  const counts = { ready: 0, needs_attention: 0, skipped: 0, unchecked: 0 }
  for (const check of args.checks) counts[check?.status ?? "unchecked"] += 1
  return counts
}

function statusText(check: RowCheck | null): string {
  if (!check) return "Changed"
  return { ready: "Ready", needs_attention: "Needs Attention", skipped: "Skipped" }[check.status]
}

// An emptied value removes the column from the row, so the fallback applies.
function withField(
  fields: Record<string, string>,
  column: string,
  value: string
): Record<string, string> {
  const { [column]: _previous, ...rest } = fields
  return value.trim() ? { ...rest, [column]: value } : rest
}

function rawRecipient(recipient: MergeRecipient): EditedRecords[number] {
  return {
    email: recipient.email,
    ...(recipient.firstName ? { first_name: recipient.firstName } : {}),
    ...(recipient.lastName ? { last_name: recipient.lastName } : {}),
    ...(Object.keys(recipient.fields).length > 0 ? { fields: recipient.fields } : {}),
  }
}
