// apps/web/src/features/conversations/components/message-shell.tsx

import type { ReactNode } from "react"
import { BotIcon, UserIcon } from "lucide-react"

import { formatTime } from "@/lib/format"

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
    <div className="group/message flex justify-end px-1 py-1">
      <div className="flex max-w-[min(42rem,86%)] flex-col items-end gap-1">
        <div className="flex items-center gap-2 text-xs">
          {pending && <span className="text-muted-foreground">Sending</span>}
          <time className="text-muted-foreground">{formatTime(createdAt)}</time>
          <span className="bg-primary text-primary-foreground flex size-5 items-center justify-center rounded-full">
            <UserIcon className="size-3" />
          </span>
        </div>
        <div className="bg-primary text-primary-foreground rounded-lg px-3 py-2 text-sm leading-relaxed shadow-sm">
          {children}
        </div>
      </div>
    </div>
  )
}

export function AssistantMessageShell({
  children,
  createdAt,
  label = "Agent",
  streaming,
}: {
  children: ReactNode
  createdAt: string | null
  label?: string
  streaming?: boolean
}) {
  return (
    <div className="group/message flex w-full justify-start px-1 py-2">
      <div className="flex w-full gap-3">
        <div className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-full">
          <BotIcon className="size-4" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex min-w-0 items-center gap-2 text-xs">
            <span className="truncate font-medium">{label}</span>
            {createdAt && <time className="text-muted-foreground">{formatTime(createdAt)}</time>}
            {streaming && <span className="bg-foreground/70 size-1.5 animate-pulse rounded-full" />}
          </div>
          <div className="flex min-w-0 flex-col gap-3">{children}</div>
        </div>
      </div>
    </div>
  )
}
