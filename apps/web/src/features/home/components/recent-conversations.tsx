// apps/web/src/features/home/components/recent-conversations.tsx

import { Link } from "@tanstack/react-router"
import { MessagesSquareIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import type { Conversation } from "@/features/conversations/types"
import { HomeSection } from "@/features/home/components/home-section"

const RECENT_LIMIT = 6

export function RecentConversations({ conversations }: { conversations: Conversation[] }) {
  const recent = conversations
    .filter((conversation) => !conversation.unread && !conversation.needs_approval)
    .slice(0, RECENT_LIMIT)

  if (recent.length === 0) {
    return null
  }

  return (
    <HomeSection
      action={
        <Button size="sm" variant="ghost" render={<Link to="/conversations" />}>
          View All
        </Button>
      }
      description="Pick up where you left off."
      icon={<MessagesSquareIcon aria-hidden="true" className="size-4" />}
      title="Continue Conversations"
    >
      <ConversationList conversations={recent} showRunStatus />
    </HomeSection>
  )
}
