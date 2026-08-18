// apps/web/src/features/agents/components/agent-identity-icon.tsx

import type { CSSProperties } from "react"
import { BotIcon } from "lucide-react"

import { agentIdentityColorIndex, agentIdentityIndex } from "@/lib/agent-identity"
import { cn } from "@/lib/utils"

const sizeClasses = {
  sm: { container: "size-5 rounded-md", icon: "size-3" },
  md: { container: "size-6 rounded-md", icon: "size-3.5" },
  lg: { container: "size-8 rounded-lg", icon: "size-5" },
} as const

type AgentIdentityIconProps = {
  agentId: string
  decorative?: boolean
  metadata?: Record<string, unknown> | null | undefined
  name: string
  size?: keyof typeof sizeClasses
}

export function AgentIdentityIcon({
  agentId,
  decorative = false,
  metadata,
  name,
  size = "md",
}: AgentIdentityIconProps) {
  const identityIndex = agentIdentityColorIndex(metadata) ?? agentIdentityIndex(agentId)
  const classes = sizeClasses[size]
  const style = {
    "--agent-color": `var(--agent-${String(identityIndex + 1)})`,
  } as CSSProperties

  return (
    <span
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : name}
      className={cn(
        "inline-flex shrink-0 items-center justify-center bg-linear-to-br from-(--agent-color)/95 to-(--agent-color) text-white shadow-xs",
        classes.container
      )}
      role={decorative ? undefined : "img"}
      style={style}
    >
      <BotIcon aria-hidden="true" className={classes.icon + ` stroke-white!`} strokeWidth={2.25} />
    </span>
  )
}
