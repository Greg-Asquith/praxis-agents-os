// apps/web/src/features/conversations/components/message-shell.tsx

import type { ReactNode } from "react"
import { BotIcon } from "lucide-react"
import { useSuspenseQuery } from "@tanstack/react-query"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { formatTime, initials } from "@/lib/format"

export function UserMessageShell({
  children,
  createdAt,
  pending = false,
}: {
  children: ReactNode
  createdAt: string
  pending?: boolean
}) {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const name = user.display_name ?? user.email

  return (
    <div className="group/message flex justify-end px-1">
      <div className="flex max-w-[min(42rem,86%)] flex-col items-end gap-1.5">
        <div className="text-muted-foreground flex items-center gap-2 text-xs">
          {pending && <span>Sending</span>}
          <time>{formatTime(createdAt)}</time>
          <Avatar size="sm">
            {user.avatar_url && <AvatarImage src={user.avatar_url} alt={name} />}
            <AvatarFallback>{initials(name)}</AvatarFallback>
          </Avatar>
        </div>
        <div className="bg-muted text-foreground rounded-2xl px-4 py-2.5 text-sm leading-relaxed">
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
    <div className="group/message flex w-full justify-start px-1">
      <div className="flex w-full gap-3">
        <div className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full">
          <BotIcon className="size-3.5" />
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
