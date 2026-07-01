// apps/web/src/features/conversations/components/conversation-not-found.tsx

import { Link } from "@tanstack/react-router"
import { MessageSquareTextIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

export function ConversationNotFound() {
  return (
    <div className="flex min-h-[520px] flex-col items-center justify-center p-8 text-center">
      <div className="bg-muted text-muted-foreground mb-4 flex size-11 items-center justify-center rounded-full">
        <MessageSquareTextIcon className="size-5" />
      </div>
      <h2 className="font-heading text-xl font-semibold">Conversation not found</h2>
      <p className="text-muted-foreground mt-2 max-w-md text-sm">
        The selected conversation is not available in this workspace.
      </p>
      <Button className="mt-4" variant="outline" render={<Link to="/conversations" />}>
        Back to conversations
      </Button>
    </div>
  )
}
