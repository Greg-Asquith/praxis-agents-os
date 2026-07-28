// apps/web/src/features/conversations/components/skill-document-read-row.tsx

import { FileTextIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { MarkdownContent } from "@/components/markdown/markdown-content"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { skillDocumentReadArgs } from "@/features/conversations/skills/skill-document-read"

type SkillDocumentReadRowProps = {
  activity: ToolActivity
  defaultOpen?: boolean
}

export function SkillDocumentReadRow({ activity, defaultOpen = false }: SkillDocumentReadRowProps) {
  const { document, skill } = skillDocumentReadArgs(activity.args)
  const heading = <SkillDocumentHeading />
  if (activity.status === "running") {
    return (
      <FanOutSkeleton
        heading={heading}
        label="Reading skill document…"
        summary={document ?? skill ?? "Loading guidance"}
      />
    )
  }
  if (typeof activity.result !== "string") {
    return null
  }

  const completed = activity.status === "completed"
  const details = [
    ...(skill ? [{ label: "Skill", value: skill }] : []),
    ...(document ? [{ label: "Document", value: document }] : []),
  ]
  return (
    <ToolResultCard
      ariaLabel="Skill document result"
      defaultOpen={defaultOpen}
      details={details}
      heading={heading}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      {completed ? (
        <div className="max-h-96 min-w-0 overflow-auto py-1">
          <MarkdownContent content={documentContentFromResult(activity.result)} />
        </div>
      ) : (
        <Alert variant="destructive">
          <AlertTitle>What Went Wrong</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{activity.result}</AlertDescription>
        </Alert>
      )}
    </ToolResultCard>
  )
}

function SkillDocumentHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
      <span>Read Skill Document</span>
    </span>
  )
}

function documentContentFromResult(value: string) {
  const trimmed = value.trim()
  const match = /^<skill-document\b[^>]*>\n?([\s\S]*?)\n?<\/skill-document>\s*$/.exec(trimmed)
  return match?.[1]?.trim() ?? value
}
