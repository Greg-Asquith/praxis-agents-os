// apps/web/src/integrations/mail-merge-progress.tsx

import { useQuery } from "@tanstack/react-query"
import { CheckCircle2Icon, PauseIcon, PlayIcon, XIcon } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { Progress } from "@/components/ui/progress"
import { countOf, finishText, type MailMergeResult } from "@/integrations/mail-merge"
import {
  mailMergeQueryOptions,
  useMailMergeAction,
  type MailMergeProgress,
  type MailMergeRowState,
  type MailMergeStatus,
} from "@/integrations/mail-merge-api"
import { formatTime } from "@/lib/format"

const PAGE_SIZE = 25
const ENDED: ReadonlySet<MailMergeStatus> = new Set(["completed", "cancelled", "stopped"])
const STATE_LABELS: Record<MailMergeRowState, string> = {
  waiting: "Waiting",
  sent: "Sent",
  failed: "Failed",
  unverified: "Couldn't Confirm",
  skipped: "Skipped",
}
const STATE_BADGES = {
  waiting: "secondary",
  sent: "success",
  failed: "destructive",
  unverified: "warning",
  skipped: "outline",
} as const
const REASONS: Record<string, string> = {
  do_not_email: "On the Do Not Email list",
  duplicate: "Already in the list",
  sender: "Your own address",
  needs_attention: "Needed fixing at approval",
  render_failed: "Couldn't fill in this email",
  send_failed: "The send didn't go through",
}
const UNVERIFIED_NOTE = "Check your Sent folder before sending to this person again."
const COLUMNS: DataColumn[] = [
  { key: "email", kind: "text", label: "Email" },
  { key: "result", kind: "text", label: "Result" },
  { key: "detail", kind: "text", label: "Detail" },
  { key: "sent_at", kind: "text", label: "Sent At" },
]

export function MailMergeProgressCard({
  providerName,
  result,
}: {
  providerName: string
  result: MailMergeResult
}) {
  const progress = useQuery(mailMergeQueryOptions(result.mergeId))
  if (!progress.data) return <StartedLine pending={progress.isPending} result={result} />
  return <ProgressBody progress={progress.data} providerName={providerName} />
}

function StartedLine({ pending, result }: { pending: boolean; result: MailMergeResult }) {
  return (
    <p className="text-sm" role="status">
      {pending ? "Checking progress… " : ""}
      Sending {countOf(result.sendingTo, "email")} from {result.sender} in the background
      {result.estimatedFinish ? `, finishing around ${finishText(result.estimatedFinish)}` : ""}.
    </p>
  )
}

function ProgressBody({
  progress,
  providerName,
}: {
  progress: MailMergeProgress
  providerName: string
}) {
  const { counts } = progress
  const toSend = counts.total - counts.skipped
  const settled = counts.sent + counts.failed + counts.unverified
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex min-w-0 flex-wrap items-center gap-2 text-sm" role="status">
          <StatusBadge status={progress.status} />
          <span className="text-muted-foreground">{statusDetail(progress, providerName)}</span>
        </p>
        <Controls progress={progress} />
      </div>
      {ENDED.has(progress.status) ? null : (
        <Progress aria-label="Emails sent" value={toSend > 0 ? (settled / toSend) * 100 : 0} />
      )}
      {counts.unverified > 0 ? (
        <p className="text-warning-text bg-warning/10 rounded-md px-2.5 py-2 text-sm">
          Praxis couldn&apos;t confirm whether {countOf(counts.unverified, "email")} went out. Check
          your Sent folder before sending again to these people.
        </p>
      ) : null}
      <ResultsTable progress={progress} />
    </div>
  )
}

function StatusBadge({ status }: { status: MailMergeStatus }) {
  if (status === "completed")
    return (
      <Badge variant="success">
        <CheckCircle2Icon aria-hidden="true" />
        Finished
      </Badge>
    )
  if (status === "paused") return <Badge variant="warning">Paused</Badge>
  if (status === "cancelled") return <Badge variant="secondary">Cancelled</Badge>
  if (status === "stopped") return <Badge variant="destructive">Stopped</Badge>
  return (
    <Badge variant="outline">
      <span aria-hidden="true" className="bg-primary size-1.5 animate-pulse rounded-full" />
      Sending
    </Badge>
  )
}

function statusDetail(progress: MailMergeProgress, providerName: string): string {
  const notSent = progress.counts.waiting
  const unsent = notSent > 0 ? ` The other ${countOf(notSent, "email")} weren't sent.` : ""
  const at = progress.finished_at ? ` at ${formatTime(progress.finished_at)}` : ""
  switch (progress.status) {
    case "queued":
    case "sending":
      return `One email every few seconds from ${progress.sender_address}${
        progress.estimated_finish
          ? `. Expected to finish around ${finishText(progress.estimated_finish)}`
          : ""
      }.`
    case "paused":
      return pausedDetail(progress, providerName)
    case "completed":
      return progress.counts.failed + progress.counts.unverified > 0
        ? `Finished${at}. Some emails didn't go out; they're listed below.`
        : `Finished${at}. Every email went out.`
    case "cancelled":
      return `Cancelled${at}.${unsent}`
    case "stopped":
      return `${stoppedReason(progress.stop_reason, providerName)}${unsent}`
  }
}

function pausedDetail(progress: MailMergeProgress, providerName: string): string {
  if (progress.stop_reason === "daily_limit")
    return `${providerName}'s daily sending limit was reached. Resume to carry on; emails go out when there's room${
      progress.resumes_at ? `, from around ${finishText(progress.resumes_at)}` : ""
    }.`
  if (progress.stop_reason === "reconnect")
    return `${providerName} needs reconnecting. Reconnect it in Integrations, then resume.`
  return "No more emails go out until you resume."
}

function stoppedReason(reason: string | null, providerName: string): string {
  if (reason === "repeated_failures") return "Stopped after five sends in a row failed."
  if (reason === "sender_removed")
    return "Stopped because the sender no longer has access to this workspace."
  if (reason === "platform_quota")
    return `Stopped because Praxis reached its ${providerName} sending quota for today.`
  return "Stopped after a problem sending."
}

function Controls({ progress }: { progress: MailMergeProgress }) {
  const action = useMailMergeAction(progress.id)
  const [confirmCancel, setConfirmCancel] = useState(false)
  if (ENDED.has(progress.status)) return null
  const paused = progress.status === "paused"
  return (
    <div className="grid justify-items-end gap-1">
      <div className="flex gap-2">
        <Button
          disabled={action.isPending}
          onClick={() => {
            action.mutate(paused ? "resume" : "pause")
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          {paused ? <PlayIcon aria-hidden="true" /> : <PauseIcon aria-hidden="true" />}
          {paused ? "Resume" : "Pause"}
        </Button>
        <Button
          disabled={action.isPending}
          onClick={() => {
            setConfirmCancel(true)
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <XIcon aria-hidden="true" />
          Cancel
        </Button>
      </div>
      {action.error ? (
        <p className="text-destructive max-w-xs text-right text-sm">{action.error.message}</p>
      ) : null}
      <ConfirmDialog
        confirmLabel="Cancel Mail Merge"
        description={`The ${countOf(progress.counts.waiting, "email")} not yet sent will never go out. Emails already sent stay sent.`}
        isPending={action.isPending}
        onConfirm={() => {
          action.mutate("cancel", {
            onSettled: () => {
              setConfirmCancel(false)
            },
          })
        }}
        onOpenChange={setConfirmCancel}
        open={confirmCancel}
        title="Cancel this mail merge?"
      />
    </div>
  )
}

function ResultsTable({ progress }: { progress: MailMergeProgress }) {
  const ended = ENDED.has(progress.status)
  const [tab, setTab] = useState<string | undefined>(undefined)
  const tabs: DataTableTab[] = [
    { id: "all", label: "All", match: () => true },
    ...(["failed", "unverified", "sent", "skipped", "waiting"] as const).map((state) => ({
      id: state,
      label: state === "waiting" && ended ? "Not Sent" : STATE_LABELS[state],
      match: (row: Record<string, unknown>) => row["state"] === state,
      hideWhenEmpty: true,
    })),
  ]
  return (
    <DataTable
      activeTab={tab ?? (progress.counts.failed > 0 ? "failed" : "all")}
      columns={COLUMNS}
      exportFilename="mail-merge-results.csv"
      onTabChange={setTab}
      pageSize={PAGE_SIZE}
      renderCell={(column, row) => {
        if (column.key !== "result") return null
        const state = row["state"] as MailMergeRowState
        return <Badge variant={STATE_BADGES[state]}>{row["result"] as string}</Badge>
      }}
      rowDetails={false}
      rowNoun={["recipient", "recipients"]}
      rows={progress.recipients.map((recipient) => ({
        email: recipient.email,
        state: recipient.state,
        result: recipient.state === "waiting" && ended ? "Not Sent" : STATE_LABELS[recipient.state],
        detail: rowDetail(recipient.state, recipient.reason),
        sent_at: recipient.sent_at ? formatTime(recipient.sent_at) : "",
      }))}
      searchable={progress.recipients.length > PAGE_SIZE}
      summary={<span>{resultsSummary(progress)}</span>}
      tabs={tabs}
    />
  )
}

// Such as "140 of 212 sent · 3 failed"; empty outcomes are left out.
function resultsSummary(progress: MailMergeProgress): string {
  const { counts } = progress
  const ended = ENDED.has(progress.status)
  const parts = [
    `${counts.sent.toLocaleString()} of ${(counts.total - counts.skipped).toLocaleString()} sent`,
    ...(
      [
        [counts.failed, "failed"],
        [counts.unverified, "unconfirmed"],
        [counts.waiting, ended ? "not sent" : "waiting"],
        [counts.skipped, "skipped"],
      ] as const
    )
      .filter(([count]) => count > 0)
      .map(([count, label]) => `${count.toLocaleString()} ${label}`),
  ]
  return parts.join(" · ")
}

function rowDetail(state: MailMergeRowState, reason: string | null): string {
  if (state === "unverified") return UNVERIFIED_NOTE
  if (state === "failed") return (reason && REASONS[reason]) ?? "The provider refused this email"
  if (state === "skipped") return (reason && REASONS[reason]) ?? "Not sent"
  return ""
}
