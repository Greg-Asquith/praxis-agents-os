// apps/web/src/features/conversations/components/message-shell.tsx

import type { ReactNode } from "react"

import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"

export function UserMessageShell({
  children,
  createdAt,
  pending = false,
}: {
  children: ReactNode
  createdAt: string
  pending?: boolean
}) {
  return (
    <div className="group/message flex justify-end px-1">
      <div className="flex max-w-[min(38rem,90%)] flex-col items-end gap-1.5">
        <div className="bg-muted text-foreground rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed">
          {children}
        </div>
        <div
          className={cn(
            "text-muted-foreground flex items-center gap-1.5 text-xs transition-opacity group-hover/message:opacity-100",
            pending ? "opacity-100" : "opacity-0"
          )}
        >
          {pending ? <span>Sending</span> : null}
          {pending ? <span aria-hidden="true">·</span> : null}
          <time>{formatTime(createdAt)}</time>
        </div>
      </div>
    </div>
  )
}

export function AssistantMessageShell({
  agentId,
  children,
  createdAt,
  label = "Agent",
  streaming,
}: {
  agentId: string
  children: ReactNode
  createdAt: string | null
  label?: string
  streaming?: boolean
}) {
  return (
    <div className="group/message flex w-full justify-start px-1">
      <div className="flex w-full min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <AgentIdentityIcon agentId={agentId} decorative name={label} size="sm" />
          <span className="truncate text-sm font-medium">{label}</span>
          <div className="flex min-w-0 items-center gap-2 text-xs">
            {createdAt && <time className="text-muted-foreground">{formatTime(createdAt)}</time>}
            {streaming ? (
              <span className="bg-primary size-1.5 animate-pulse rounded-full motion-reduce:animate-none" />
            ) : null}
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-3">{children}</div>
      </div>
    </div>
  )
}
