// apps/web/src/features/knowledge/components/source-type-badge.tsx

import { Badge } from "@/components/ui/badge"
import type { KbSourceType } from "@/features/knowledge/types"

const SOURCE_LABEL: Record<KbSourceType, string> = {
  upload: "Upload",
  url: "URL",
  manual: "Manual",
  conversation: "Conversation",
  integration: "Integration",
}

export function SourceTypeBadge({ sourceType }: { sourceType: KbSourceType }) {
  return <Badge variant="outline">{SOURCE_LABEL[sourceType]}</Badge>
}
