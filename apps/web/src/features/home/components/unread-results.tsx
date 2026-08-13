// apps/web/src/features/home/components/unread-results.tsx

import { ConversationList } from "@/features/conversations/components/conversation-list"
import type { Conversation } from "@/features/conversations/types"
import { HomeSection } from "@/features/home/components/home-section"

export function UnreadResults({ conversations }: { conversations: Conversation[] }) {
  const unreadResults = conversations.filter(
    (conversation) => conversation.unread && !conversation.needs_approval
  )

  if (unreadResults.length === 0) {
    return null
  }

  return (
    <HomeSection
      description="Agent work that came back while you were away."
      title="Unread Conversations"
    >
      <ConversationList className="lg:grid-cols-2" conversations={unreadResults} showRunStatus />
    </HomeSection>
  )
}
