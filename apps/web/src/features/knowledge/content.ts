// apps/web/src/features/knowledge/content.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { KbContent } from "@/features/knowledge/types"

export function knowledgeContentText(content: KbContent | null) {
  if (content === null) {
    return null
  }
  return nodeText(content)
}
