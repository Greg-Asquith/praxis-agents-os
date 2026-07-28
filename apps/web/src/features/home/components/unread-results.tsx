// apps/web/src/features/home/components/unread-results.tsx

import { SparklesIcon } from "lucide-react"

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
      icon={<SparklesIcon aria-hidden="true" className="size-4" />}
      title="Unread Conversations"
    >
      <ConversationList conversations={unreadResults} showRunStatus />
    </HomeSection>
  )
}
