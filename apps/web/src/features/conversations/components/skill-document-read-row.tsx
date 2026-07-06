// apps/web/src/features/conversations/components/skill-document-read-row.tsx

import { FileTextIcon } from "lucide-react"

import { JsonBlock, TextBlock } from "@/features/conversations/components/tool-call-content-blocks"
import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import { ActivityStatusIcon } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { skillDocumentReadArgs } from "@/features/conversations/skill-document-read"

type SkillDocumentReadRowProps = {
  activity: ToolActivity
  compact?: boolean
  defaultOpen?: boolean
}

export function SkillDocumentReadRow({
  activity,
  compact = false,
  defaultOpen = false,
}: SkillDocumentReadRowProps) {
  const { document, skill } = skillDocumentReadArgs(activity.args)
  const label = document
    ? `Read skill document: ${document}`
    : skill
      ? `Read skill document for ${skill}`
      : "Read skill document"
  const hasResultContent = activity.result !== undefined && activity.result !== null
  const header = (
    <ToolActivityRowHeader
      expandable={hasResultContent}
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FileTextIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">{label}</span>
        </span>
      }
      reserveChevronSpace={hasResultContent}
      suffix={null}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={defaultOpen}
      expandable={hasResultContent}
      header={header}
    >
      {hasResultContent ? <ResultBlock status={activity.status} value={activity.result} /> : null}
    </ToolActivityRowShell>
  )
}

function ResultBlock({ status, value }: { status: ToolActivity["status"]; value: unknown }) {
  if (typeof value === "string") {
    if (status === "completed") {
      return <DocumentContentBlock content={documentContentFromResult(value)} />
    }

    return <TextBlock label="Result" value={value} />
  }

  return <JsonBlock label="Result" value={value} />
}

function DocumentContentBlock({ content }: { content: string }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">Document content</p>
      <div className="bg-muted/40 border-border/70 max-h-96 min-w-0 overflow-auto rounded-md border p-3">
        <MessageMarkdown content={content} />
      </div>
    </div>
  )
}

function documentContentFromResult(value: string) {
  const trimmed = value.trim()
  const match = /^<skill-document\b[^>]*>\n?([\s\S]*?)\n?<\/skill-document>\s*$/.exec(trimmed)
  return match?.[1]?.trim() ?? value
}
