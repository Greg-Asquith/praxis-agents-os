// apps/web/src/features/conversations/components/skill-activation-row.tsx

import { useQuery } from "@tanstack/react-query"
import { SparklesIcon } from "lucide-react"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  internalSkillLabelFromCapabilityArgs,
  LOAD_SKILL_TOOL_NAME,
  loadedSkillNameFromArgs,
  skillActivationDisplayName,
} from "@/features/conversations/skills/skill-activation"
import { skillsQueryOptions } from "@/features/skills/api/list-skills"

type SkillActivationRowProps = {
  activity: ToolActivity
}

export function SkillActivationRow({ activity }: SkillActivationRowProps) {
  const skillName =
    activity.name === LOAD_SKILL_TOOL_NAME ? loadedSkillNameFromArgs(activity.args) : null
  const internalLabel = internalSkillLabelFromCapabilityArgs(activity.args)
  const skillsQuery = useQuery({
    ...skillsQueryOptions({ includeInactive: true }),
    enabled: skillName !== null,
  })
  if (!skillName && !internalLabel) {
    return null
  }

  // A workspace skill shadows a shared skill with the same name, matching the runtime.
  const matches = skillsQuery.data?.skills.filter((item) => item.name === skillName) ?? []
  const skill = matches.find((item) => item.scope === "workspace") ?? matches[0]
  const label = internalLabel ?? skillActivationDisplayName(skill, skillName ?? "")
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
