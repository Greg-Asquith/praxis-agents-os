// apps/web/src/features/conversations/components/conversation-stating-notice.tsx

import { CircleDashedIcon, MessageSquarePlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function NoActiveAgentsAlert() {
  return (
    <Alert className="max-w-lg text-left">
      <MessageSquarePlusIcon />
      <AlertTitle>No active agents</AlertTitle>
      <AlertDescription>
        Activate an agent before starting a workspace conversation.
      </AlertDescription>
    </Alert>
  )
}

export function ConversationStartingNotice() {
  return (
    <div className="text-muted-foreground flex items-center gap-2 p-4 text-sm">
      <CircleDashedIcon aria-hidden="true" className="size-4 animate-spin" />
      Starting your conversation
    </div>
  )
}
