// apps/web/src/features/conversations/components/skill-document-read-row.tsx

import { FileTextIcon } from "lucide-react"

import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import { ToolField } from "@/features/conversations/components/tool-field"
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

    return (
      <ToolField field={{ key: "result", label: "What Went Wrong", value, format: "multiline" }} />
    )
  }

  return (
    <ToolField
      field={{
        key: "result",
        label: "Result",
        value: "The document response could not be displayed.",
        format: "text",
      }}
    />
  )
}

function DocumentContentBlock({ content }: { content: string }) {
  return (
    <ToolField
      field={{ key: "content", label: "Document Content", value: content, format: "markdown" }}
    >
      <div className="max-h-96 min-w-0 overflow-auto py-1">
        <MessageMarkdown content={content} />
      </div>
    </ToolField>
  )
}

function documentContentFromResult(value: string) {
  const trimmed = value.trim()
  const match = /^<skill-document\b[^>]*>\n?([\s\S]*?)\n?<\/skill-document>\s*$/.exec(trimmed)
  return match?.[1]?.trim() ?? value
}
