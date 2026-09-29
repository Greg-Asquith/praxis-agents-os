// apps/web/src/features/conversations/components/skill-activation-row.tsx

import { SparklesIcon } from "lucide-react"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { internalSkillLabelFromCapabilityArgs } from "@/features/conversations/skills/skill-activation"

type SkillActivationRowProps = {
  activity: ToolActivity
}

export function SkillActivationRow({ activity }: SkillActivationRowProps) {
  const label = internalSkillLabelFromCapabilityArgs(activity.args)
  if (!label) {
    return null
  }
  return (
    <ToolResultCard
      ariaLabel={`Activated skill: ${label}`}
      expandable={false}
      heading={
        <span className="inline-flex min-w-0 items-center gap-2 p-2">
          <SparklesIcon className="text-muted-foreground size-4 shrink-0" />
          <span className="truncate">Activated Skill: {label}</span>
        </span>
      }
      trailing={<ActivityStatusBadge status={activity.status} />}
    />
  )
}
