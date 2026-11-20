// apps/web/src/features/memories/components/memory-origin-badge.tsx

import { useSuspenseQuery } from "@tanstack/react-query"
import { BotIcon, SparklesIcon, UserPenIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { memoryOrigin, memoryOriginLabel } from "@/features/memories/components/memory-display"
import type { Memory } from "@/features/memories/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

const ORIGIN_ICONS = {
  learned: SparklesIcon,
  agent: BotIcon,
  person: UserPenIcon,
} as const

export function MemoryOriginBadge({ memory }: { memory: Memory }) {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { workspace } = useActiveWorkspace()
  const label = memoryOriginLabel(memory, {
    userId: user.id,
    isPersonalWorkspace: workspace.is_personal,
  })
  const origin = memoryOrigin(memory)
  const Icon = ORIGIN_ICONS[origin]
  return (
    <Badge variant={origin === "learned" ? "secondary" : "outline"}>
      <Icon aria-hidden="true" data-icon="inline-start" />
      {label}
    </Badge>
  )
}
