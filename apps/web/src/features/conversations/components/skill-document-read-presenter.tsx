// apps/web/src/features/conversations/components/skill-document-read-presenter.tsx

import { SkillDocumentReadRow } from "@/features/conversations/components/skill-document-read-row"
import { READ_SKILL_DOCUMENT_TOOL_NAME } from "@/features/conversations/skills/skill-document-read"
import type { ToolRowPresenter } from "@/integrations/contract"

export const skillDocumentReadPresenter: ToolRowPresenter = {
  key: "skill-document-read",
  matches: (activity) => activity.name === READ_SKILL_DOCUMENT_TOOL_NAME,
  render: ({ activity, defaultOpen }) => (
    <SkillDocumentReadRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
