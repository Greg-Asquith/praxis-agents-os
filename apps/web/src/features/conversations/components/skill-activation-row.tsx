// apps/web/src/features/conversations/components/skill-activation-row.tsx

import { useQuery } from "@tanstack/react-query"
import { SparklesIcon } from "lucide-react"

import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import { ActivityStatusIcon } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  skillActivationDisplayName,
  skillIdFromCapabilityArgs,
} from "@/features/conversations/skill-activation"
import { skillsQueryOptions } from "@/features/skills/api/list-skills"

type SkillActivationRowProps = {
  activity: ToolActivity
  compact?: boolean
}

export function SkillActivationRow({ activity, compact = false }: SkillActivationRowProps) {
  const skillId = skillIdFromCapabilityArgs(activity.args)
  const skillsQuery = useQuery({
    ...skillsQueryOptions({ includeInactive: true }),
    enabled: skillId !== null,
  })
  if (!skillId) {
    return null
  }

  const skill = skillsQuery.data?.skills.find((item) => item.id === skillId)
  const label = skillActivationDisplayName(skill, skillId)
  const header = (
    <ToolActivityRowHeader
      expandable={false}
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <SparklesIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Activated Skill: {label}</span>
        </span>
      }
      reserveChevronSpace={false}
      suffix={null}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={false} expandable={false} header={header}>
      {null}
    </ToolActivityRowShell>
  )
}
