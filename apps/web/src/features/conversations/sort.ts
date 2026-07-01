// apps/web/src/features/conversations/sort.ts

import type { Conversation } from "@/features/conversations/types"

export function sortConversations(conversations: Conversation[]) {
  return [...conversations].sort((left, right) => {
    const leftTime = Date.parse(left.last_message_at ?? left.updated_at)
    const rightTime = Date.parse(right.last_message_at ?? right.updated_at)
    return rightTime - leftTime
  })
}
